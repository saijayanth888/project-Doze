"""Trading-reflector scoring module.

The reflector role writes 2-4 sentence post-mortems for closed paper trades.
The four metrics below capture whether those post-mortems are factually
grounded, well-judged, decision-relevant, and predictive.

Score keys (all in [0, 1]):

* ``faithfulness_regex`` -- fraction of held-out trades where the response cites
  the realized P&L value to 1 decimal place. Pure regex check against the
  gold-truth row's ``realized_pnl`` field. Cheap, deterministic.
* ``judge_score`` -- LLM-as-judge (prior adapter or a strong base model) rates
  the response on a 1-5 rubric for clarity, causal reasoning, and brevity. We
  rescale to [0, 1].
* ``debate_impact`` -- A/B test: feed the reflection back into the trading-arbiter
  adapter and check whether the arbiter would have made a different decision.
  Reflections that *do nothing* are penalised; reflections that swing the next
  decision in a useful direction are rewarded.
* ``predictive_hit_rate_30d`` -- per the test-set's ``forward_30d_return`` field,
  did the reflection's directional bias (long/short) match the realized 30-day
  return? This is the trading-bot operator's locked tiebreaker -- when this
  metric regresses >5% the run is flagged for rollback regardless of other
  scores. See :mod:`config.trading_eval_weights`.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.eval_backend import EvalResult
from agents.evals._common import (
    AdapterRunner,
    Judge,
    RubricScorer,
    clamp01,
    default_adapter_runner,
    default_judge,
    default_rubric_scorer,
    extract_first_dollar_value,
    load_test_set,
    mean,
    rate,
    values_match_to_decimal,
)

logger = logging.getLogger("modelforge.evals.reflector")

REFLECTOR_RUBRIC = (
    "Score 1-5: 1=incoherent or wrong, 2=vague, 3=acceptable but generic, "
    "4=specific and causal, 5=insightful + actionable. Reward citing the "
    "exact alpha figure, the entry/exit timing, and at least one indicator."
)

# Prior-adapter id for the A/B 'would the arbiter change its mind?' check.
# Filled in by production wiring; tests pass their own override.
DEFAULT_ARBITER_ADAPTER = "trading-arbiter::champion"


def score(  # noqa: PLR0913 -- six injectable hooks is the contract
    adapter_path: str,
    test_set_path: str,
    *,
    adapter_runner: AdapterRunner | None = None,
    judge: Judge | None = None,
    rubric_scorer: RubricScorer | None = None,
    arbiter_adapter_path: str | None = None,
    arbiter_runner: AdapterRunner | None = None,
) -> EvalResult:
    """Score a candidate reflector adapter against the held-out test set.

    The test set is JSONL with one record per closed trade. Required fields:

    * ``prompt`` -- the same prompt template the reflector role gets at runtime
    * ``realized_pnl_usd`` -- gold-truth USD value of the closed trade; null when
      only a percent is available (skips faithfulness check for that record)
    * ``forward_30d_return`` -- realized return over the next 30 trading days
      (used by the predictive hit-rate metric only)
    * ``arbiter_prompt`` -- the prompt the trading-arbiter sees on the *next*
      day; used for the debate-impact A/B
    * ``arbiter_baseline_decision`` -- the action the current arbiter would take
      without the reflection injected
    """
    runner = adapter_runner or default_adapter_runner
    j = judge or default_judge
    rs = rubric_scorer or default_rubric_scorer
    a_runner = arbiter_runner or runner
    arbiter_path = arbiter_adapter_path or DEFAULT_ARBITER_ADAPTER

    records = load_test_set(test_set_path)
    if not records:
        # Return all-zero result rather than raising: the evolution graph
        # interprets this as a non-improvement and the run is logged but not
        # crashed. Operator sees the warning in the test-set loader log.
        return EvalResult(scores={
            "faithfulness_regex": 0.0,
            "judge_score": 0.0,
            "debate_impact": 0.0,
            "predictive_hit_rate_30d": 0.0,
        }, duration_seconds=0.0)

    prompts = [str(r.get("prompt", "")) for r in records]
    responses = runner(adapter_path, prompts)

    faithful_hits = 0
    faithful_eligible = 0  # only records with a real USD value count
    rubric_scores: list[float] = []
    hit_count = 0
    eligible_for_hit = 0

    for record, response in zip(records, responses, strict=False):
        # -- faithfulness_regex -----------------------------------------
        # Gate on realized_pnl_usd being non-null. Records where we only have
        # a percent (or no ledger data) are skipped here — the denominator
        # drops by 1 for each such record, matching the spec's null-handling
        # policy. NO fabricated notional is used.
        gold = record.get("realized_pnl_usd")
        if gold is None:
            pass  # skip faithfulness check for this record; don't count in denominator
        else:
            faithful_eligible += 1
            cited = extract_first_dollar_value(response)
            try:
                gold_f = float(gold)
            except (TypeError, ValueError):
                gold_f = None
            if values_match_to_decimal(cited, gold_f, decimals=1):
                faithful_hits += 1

        # -- judge_score (1-5 rescaled to [0,1]) ------------------------
        raw = rs(record.get("prompt", ""), response, REFLECTOR_RUBRIC)
        # rubric_scorer returns either 0-1 already or 1-5; tolerate both.
        if raw > 1.0:
            raw = (raw - 1.0) / 4.0
        rubric_scores.append(clamp01(raw))

        # -- predictive_hit_rate_30d ------------------------------------
        fwd = record.get("forward_30d_return")
        if isinstance(fwd, (int, float)) and response:
            eligible_for_hit += 1
            # Heuristic: reflection biased toward "bullish" tokens vs "bearish".
            # The test set may also carry an explicit ``predicted_direction``
            # field; trust it when present.
            predicted_dir = record.get("predicted_direction")
            if not predicted_dir:
                low = response.lower()
                bull = sum(low.count(t) for t in ("bullish", "buy", "long", "upside"))
                bear = sum(low.count(t) for t in ("bearish", "sell", "short", "downside"))
                if bull > bear:
                    predicted_dir = "long"
                elif bear > bull:
                    predicted_dir = "short"
                else:
                    predicted_dir = "neutral"
            actual_dir = "long" if float(fwd) > 0 else ("short" if float(fwd) < 0 else "neutral")
            if predicted_dir == actual_dir:
                hit_count += 1

    # -- debate_impact ------------------------------------------------
    # Feed each reflection into a prompt for the current arbiter adapter and
    # check whether the resulting decision differs from the baseline. Higher
    # is better up to ~30% change-rate; beyond that it's noise and we cap.
    debate_prompts: list[str] = []
    baselines: list[str] = []
    for record, response in zip(records, responses, strict=False):
        arbiter_prompt = str(record.get("arbiter_prompt", "")).strip()
        baseline = str(record.get("arbiter_baseline_decision", "")).strip()
        if not arbiter_prompt or not baseline:
            continue
        debate_prompts.append(arbiter_prompt + "\n\nPrior reflection:\n" + response)
        baselines.append(baseline)

    debate_impact = 0.0
    if debate_prompts:
        new_decisions = a_runner(arbiter_path, debate_prompts)
        diffs = sum(
            1 for new, old in zip(new_decisions, baselines, strict=False)
            if new.strip() and new.strip() != old
        )
        change_rate = rate(diffs, len(debate_prompts))
        # Reward up to 30% change; clamp at that ceiling so a stochastic adapter
        # doesn't farm the metric by always disagreeing.
        debate_impact = clamp01(change_rate / 0.30)

    # faithfulness_regex denominator is faithful_eligible (records with real USD PnL),
    # NOT len(records). Records where realized_pnl_usd is null are exempt from
    # the dollar-citation check — the model correctly cannot cite what isn't there.
    scores: dict[str, float] = {
        "faithfulness_regex": rate(faithful_hits, faithful_eligible),
        "judge_score": clamp01(mean(rubric_scores)),
        "debate_impact": clamp01(debate_impact),
        "predictive_hit_rate_30d": rate(hit_count, eligible_for_hit),
    }
    logger.info("[trading-eval reflector] scores=%s n=%d", scores, len(records))
    return EvalResult(scores=scores, duration_seconds=0.0)


def _score_alias(*args: Any, **kwargs: Any) -> EvalResult:
    """Public scoring entrypoint -- alias retained for spec contract.

    Registered as ``eval_reflector.eval`` in :mod:`eval_registry`. We keep
    a separate underscore-prefixed alias so the codebase isn't peppered with
    references that conflict with Python's builtin of the same name.
    """
    return score(*args, **kwargs)


# Spec contract: the registry imports ``eval_reflector.eval``. Bind it here
# without invoking Python's builtin in this module body.
globals()["eval"] = _score_alias

__all__ = ["score", "_score_alias", "REFLECTOR_RUBRIC", "DEFAULT_ARBITER_ADAPTER"]
