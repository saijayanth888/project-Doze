"""Trading-arbiter (Portfolio Manager) scoring module.

The arbiter is the most consequential role: it emits a structured
``TraderProposal`` that drives a paper / live trade. Three metrics:

* ``structured_output_validity_rate`` -- fraction of responses that parse as
  ``TraderProposal``. Below ~0.9 means the role is broken for production.
* ``decision_consistency`` -- run the same prompt ``N`` times at temperature=0
  and check that the action+ticker+horizon are identical. Catches a class of
  silent regressions where the adapter starts hallucinating different tickers
  on identical evidence.
* ``downstream_pnl_per_decision`` -- the test set carries the realized 5-day
  P&L of the recommended action for each held-out example. We normalise via
  sigmoid around $0 so the score lives in [0, 1] and feeds Pareto cleanly.

Per trading-bot's locked decision #3, ``downstream_pnl_per_decision`` is the
arbiter's Pareto tiebreaker (see :mod:`config.trading_eval_weights`).
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from agents.eval_backend import EvalResult
from agents.evals._common import (
    AdapterRunner,
    clamp01,
    default_adapter_runner,
    load_test_set,
    mean,
    rate,
)
from agents.evals.trading_schemas import TraderProposal

logger = logging.getLogger("modelforge.evals.arbiter")

# How many runs per prompt to check decision consistency. 3 is the sweet spot:
# enough to detect non-determinism without 3x'ing eval cost.
DEFAULT_CONSISTENCY_N = 3

# Sigmoid scale: $1,000 of 5-day P&L maps to ~0.88, -$1,000 to ~0.12,
# 0 to 0.5. Tunable via :mod:`config.trading_eval_weights`.
PNL_SIGMOID_SCALE_USD = 500.0


def _parse_proposal(text: str) -> TraderProposal | None:
    """Best-effort JSON-block extraction + Pydantic validation."""
    if not isinstance(text, str) or not text.strip():
        return None
    # Strip markdown code fences if the adapter wrapped its JSON.
    cleaned = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    # Find the first {...} block.
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        return None
    blob = m.group(0)
    try:
        return TraderProposal.model_validate_json(blob)
    except Exception as exc:  # pydantic.ValidationError + JSON errors
        logger.debug("[trading-eval arbiter] proposal parse failed: %s", exc)
        return None


def _pnl_to_score(pnl_usd: float) -> float:
    """Logistic squash so P&L lives in [0, 1] for Pareto comparison.

    ``+PNL_SIGMOID_SCALE_USD`` maps to ~0.731, ``-PNL_SIGMOID_SCALE_USD`` to
    ~0.269, ``0`` to ``0.5``. Symmetric, monotonic.
    """
    try:
        x = float(pnl_usd) / PNL_SIGMOID_SCALE_USD
    except (TypeError, ValueError):
        return 0.5
    # Clamp the exponent to keep math.exp finite for absurd inputs.
    if x > 50:
        return 1.0
    if x < -50:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def score(
    adapter_path: str,
    test_set_path: str,
    *,
    adapter_runner: AdapterRunner | None = None,
    consistency_n: int = DEFAULT_CONSISTENCY_N,
) -> EvalResult:
    """Score a candidate arbiter adapter against the held-out test set.

    Test-set required fields (JSONL one record per arbitration):

    * ``prompt`` -- the full arbiter prompt with the debate + evidence bundle
    * ``forward_5d_pnl_usd`` -- realized $ P&L of the recommended action over
      the next 5 trading days. May be negative.
    """
    runner = adapter_runner or default_adapter_runner

    records = load_test_set(test_set_path)
    if not records:
        return EvalResult(scores={
            "structured_output_validity_rate": 0.0,
            "decision_consistency": 0.0,
            "downstream_pnl_per_decision": 0.5,
        }, duration_seconds=0.0)

    prompts = [str(r.get("prompt", "")) for r in records]
    responses = runner(adapter_path, prompts)

    # -- structured_output_validity_rate -----------------------------------
    parsed: list[TraderProposal | None] = [_parse_proposal(r) for r in responses]
    valid = sum(1 for p in parsed if p is not None)

    # -- decision_consistency ----------------------------------------------
    # Re-run each prompt consistency_n times and check whether action+ticker
    # are stable. This is genuinely the hot path for an arbiter eval, so we
    # only do it on records that parsed validly the first time -- a busted
    # proposal will be busted N times, no signal there.
    consistent_records = 0
    eligible_for_consistency = 0
    for prompt, first_parsed in zip(prompts, parsed, strict=False):
        if first_parsed is None:
            continue
        eligible_for_consistency += 1
        # consistency_n - 1 extra calls because we already have the first one.
        extra = consistency_n - 1
        if extra <= 0:
            consistent_records += 1
            continue
        extra_responses = runner(adapter_path, [prompt] * extra)
        extra_parsed = [_parse_proposal(r) for r in extra_responses]
        signature = (first_parsed.action, first_parsed.ticker, first_parsed.horizon_days)
        all_match = all(
            p is not None
            and (p.action, p.ticker, p.horizon_days) == signature
            for p in extra_parsed
        )
        if all_match:
            consistent_records += 1

    # -- downstream_pnl_per_decision ---------------------------------------
    # For records where the adapter produced a valid proposal, look up the
    # gold-truth 5-day P&L. Average the sigmoid-squashed values.
    pnl_scores: list[float] = []
    for record, prop in zip(records, parsed, strict=False):
        if prop is None:
            # An unparseable proposal counts as a 'no-decision' -> neutral 0.5.
            pnl_scores.append(0.5)
            continue
        pnl = record.get("forward_5d_pnl_usd")
        if not isinstance(pnl, (int, float)):
            pnl_scores.append(0.5)
            continue
        # Honor the proposal's intended direction: if the adapter said "sell"
        # but the realized PnL is the *long*-side outcome, flip the sign so
        # the metric correctly rewards "short into a drop".
        signed_pnl = float(pnl)
        if prop.action == "sell":
            signed_pnl = -signed_pnl
        elif prop.action in ("hold", "close"):
            # Hold/close don't have a directional P&L claim; collapse to neutral.
            signed_pnl = 0.0
        pnl_scores.append(_pnl_to_score(signed_pnl))

    scores: dict[str, float] = {
        "structured_output_validity_rate": rate(valid, len(records)),
        "decision_consistency": rate(consistent_records, eligible_for_consistency),
        "downstream_pnl_per_decision": clamp01(mean(pnl_scores) if pnl_scores else 0.5),
    }
    logger.info(
        "[trading-eval arbiter] scores=%s n=%d valid=%d consistent=%d",
        scores, len(records), valid, consistent_records,
    )
    return EvalResult(scores=scores, duration_seconds=0.0)


def _score_alias(*args: Any, **kwargs: Any) -> EvalResult:
    """Public scoring entrypoint. See module docstring."""
    return score(*args, **kwargs)


# Spec contract: the registry imports ``eval_arbiter.eval``.
globals()["eval"] = _score_alias


__all__ = [
    "score",
    "_score_alias",
    "DEFAULT_CONSISTENCY_N",
    "PNL_SIGMOID_SCALE_USD",
    "_parse_proposal",
    "_pnl_to_score",
]
