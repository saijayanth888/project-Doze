"""Trading-bull / trading-bear scoring module.

The bull and bear roles each produce a prose argument for / against a trade.
We score them on three trading-meaningful axes:

* ``evidence_density`` -- count of price tags, percent-moves, indicator names,
  and ISO dates per 100 tokens. A debater that asserts without numbers is
  hand-waving; one that cites the input bundle is grounded. Capped so a
  response that's *only* numbers doesn't dominate.
* ``opponent_acknowledgment_rate`` -- per record, the test set carries the
  ``opponent_strongest_point`` (a short tag like "RSI oversold" or
  "Q3 revenue miss"). Did the response name it explicitly? Required for both
  sides because trading-bot's debate format penalises one-sided dismissal.
* ``judge_preference`` -- pairwise LLM-as-judge prefers this response over the
  prior adapter's response to the same prompt. Returns a win-rate in [0, 1];
  0.5 = tie.

Used by both ``trading-bull`` and ``trading-bear`` tracks via the ``role`` arg.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from agents.eval_backend import EvalResult
from agents.evals._common import (
    AdapterRunner,
    Judge,
    clamp01,
    count_evidence_tokens,
    default_adapter_runner,
    default_judge,
    load_test_set,
    mean,
    mentions_token,
    rate,
)

logger = logging.getLogger("modelforge.evals.debater")

# How much evidence per 100 tokens is "fully dense"? Calibrated against the
# top-quartile bull/bear samples in trading-bot's training corpus (~3 evidence
# tokens per 100 prose tokens). Anything above this saturates the metric.
EVIDENCE_DENSITY_TARGET_PER_100_TOKENS = 3.0


def score(  # noqa: PLR0913 -- six injectable hooks is the contract
    adapter_path: str,
    test_set_path: str,
    *,
    role: Literal["bull", "bear"],
    adapter_runner: AdapterRunner | None = None,
    prior_adapter_path: str | None = None,
    prior_runner: AdapterRunner | None = None,
    judge: Judge | None = None,
) -> EvalResult:
    """Score a candidate bull/bear adapter against the held-out test set.

    Test-set required fields (JSONL one record per debate turn):

    * ``prompt`` -- the debater prompt with the input bundle attached
    * ``opponent_strongest_point`` -- short string the response should
      acknowledge (e.g. ``"RSI oversold at 22"``)

    Optional:

    * ``prior_response`` -- the prior adapter's response. When absent, we
      generate one by calling ``prior_runner(prior_adapter_path, prompts)``.
    """
    if role not in ("bull", "bear"):
        raise ValueError(f"role must be 'bull' or 'bear', got {role!r}")

    runner = adapter_runner or default_adapter_runner
    p_runner = prior_runner or runner
    j = judge or default_judge

    records = load_test_set(test_set_path)
    if not records:
        return EvalResult(scores={
            "evidence_density": 0.0,
            "opponent_acknowledgment_rate": 0.0,
            "judge_preference": 0.5,
        }, duration_seconds=0.0)

    prompts = [str(r.get("prompt", "")) for r in records]
    responses = runner(adapter_path, prompts)

    # -- prior responses for the pairwise judge ---------------------------
    prior_responses: list[str] = []
    embedded_priors = [r.get("prior_response") for r in records]
    if all(isinstance(x, str) and x for x in embedded_priors):
        prior_responses = [str(x) for x in embedded_priors]
    elif prior_adapter_path:
        prior_responses = p_runner(prior_adapter_path, prompts)
    else:
        # No prior at all -> treat every comparison as a tie.
        prior_responses = ["" for _ in prompts]

    # -- evidence_density --------------------------------------------------
    densities: list[float] = []
    for response in responses:
        counts = count_evidence_tokens(response)
        total_evidence = sum(counts.values())
        # Token approximation: 1 token ~ 4 chars. Cheap and good enough for
        # density normalisation; lm-eval doesn't tokenise here either.
        approx_tokens = max(1, len(response) // 4)
        per_100 = (total_evidence * 100.0) / approx_tokens
        densities.append(clamp01(per_100 / EVIDENCE_DENSITY_TARGET_PER_100_TOKENS))

    # -- opponent_acknowledgment_rate --------------------------------------
    ack_hits = 0
    ack_eligible = 0
    for record, response in zip(records, responses, strict=False):
        point = str(record.get("opponent_strongest_point") or "").strip()
        if not point:
            continue
        ack_eligible += 1
        # Normalise: a debater satisfies the metric by naming any non-trivial
        # subtoken from the opponent's claim (>=3 chars). Avoids penalising
        # paraphrase.
        tokens = [t for t in point.split() if len(t) >= 3]
        if not tokens:
            if mentions_token(response, point):
                ack_hits += 1
            continue
        if any(mentions_token(response, t) for t in tokens):
            ack_hits += 1

    # -- judge_preference --------------------------------------------------
    wins = 0.0
    judged = 0
    for prompt, child_resp, prior_resp in zip(prompts, responses, prior_responses, strict=False):
        if not prior_resp:
            # No prior -> can't compare. Skip rather than counting as a tie
            # so the mean isn't pulled toward 0.5 by missing data.
            continue
        try:
            pref = float(j(prompt, child_resp, prior_resp))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[trading-eval debater] judge raised: %s", exc)
            continue
        wins += clamp01(pref)
        judged += 1

    judge_pref = (wins / judged) if judged > 0 else 0.5

    scores: dict[str, float] = {
        "evidence_density": clamp01(mean(densities)),
        "opponent_acknowledgment_rate": rate(ack_hits, ack_eligible),
        "judge_preference": clamp01(judge_pref),
    }
    logger.info(
        "[trading-eval %s] scores=%s n=%d", role, scores, len(records),
    )
    return EvalResult(scores=scores, duration_seconds=0.0)


def _score_alias(*args: Any, **kwargs: Any) -> EvalResult:
    """Public scoring entrypoint. See module docstring for spec contract."""
    return score(*args, **kwargs)


# Spec contract: the registry imports ``eval_debater.eval``.
globals()["eval"] = _score_alias


__all__ = ["score", "_score_alias", "EVIDENCE_DENSITY_TARGET_PER_100_TOKENS"]
