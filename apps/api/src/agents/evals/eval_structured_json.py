"""Structured-JSON scoring module (regime-tagger + indicator-selector).

Both roles share the same scoring shape: emit a JSON blob matching a Pydantic
schema, judged on (a) whether it validates and (b) whether it agrees with a
baseline classifier.

* ``structured_output_validity_rate`` -- fraction parsing against ``schema``.
* ``agreement_with_baseline`` -- per record the test set carries a
  ``baseline_output`` dict (HMM regime label for the regime-tagger; hardcoded
  indicator ranking for the indicator-selector). We measure agreement on the
  semantically meaningful fields (regime / chosen indicator set).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel

from agents.eval_backend import EvalResult
from agents.evals._common import (
    AdapterRunner,
    default_adapter_runner,
    load_test_set,
    rate,
)
from agents.evals.trading_schemas import IndicatorSelection, RegimeTag

logger = logging.getLogger("modelforge.evals.structured_json")


def _extract_json_blob(text: str) -> str | None:
    """Pull the first ``{...}`` blob from text. Strips code fences first."""
    if not isinstance(text, str) or not text.strip():
        return None
    cleaned = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    return m.group(0) if m else None


def _agreement_for(parsed: BaseModel, baseline: dict[str, Any]) -> bool:
    """Schema-specific agreement check.

    * ``RegimeTag``: regime label matches case-insensitively. We don't compare
      confidence -- the baseline HMM doesn't produce a comparable confidence.
    * ``IndicatorSelection``: Jaccard >= 0.5 over the indicator set. Strict
      equality is too harsh; 0.5 overlap means the model + baseline at least
      agree on the strategy family.
    """
    if isinstance(parsed, RegimeTag):
        base_regime = str(baseline.get("regime", "")).strip().lower()
        return base_regime == parsed.regime.lower()
    if isinstance(parsed, IndicatorSelection):
        base_ind = baseline.get("indicators") or []
        if not isinstance(base_ind, list):
            return False
        a = {str(x).strip().lower() for x in base_ind}
        b = set(parsed.indicators)
        if not a or not b:
            return False
        jaccard = len(a & b) / len(a | b)
        return jaccard >= 0.5
    # Unknown schema -> can't compare meaningfully.
    return False


def score(
    adapter_path: str,
    test_set_path: str,
    *,
    schema: type[BaseModel],
    adapter_runner: AdapterRunner | None = None,
) -> EvalResult:
    """Score a candidate structured-JSON adapter.

    Test-set required fields (JSONL one record per call):

    * ``prompt`` -- the prompt the role gets at runtime
    * ``baseline_output`` -- dict with the baseline classifier's output for the
      same input (HMM regime, hardcoded indicator ranking, etc.)
    """
    runner = adapter_runner or default_adapter_runner

    records = load_test_set(test_set_path)
    if not records:
        return EvalResult(scores={
            "structured_output_validity_rate": 0.0,
            "agreement_with_baseline": 0.0,
        }, duration_seconds=0.0)

    prompts = [str(r.get("prompt", "")) for r in records]
    responses = runner(adapter_path, prompts)

    valid_count = 0
    agreement_count = 0
    agreement_eligible = 0

    for record, response in zip(records, responses, strict=False):
        blob = _extract_json_blob(response)
        if blob is None:
            continue
        try:
            parsed = schema.model_validate_json(blob)
        except Exception as exc:  # pydantic.ValidationError + JSON errors
            logger.debug("[trading-eval json] %s parse failed: %s", schema.__name__, exc)
            continue
        valid_count += 1
        baseline = record.get("baseline_output")
        if not isinstance(baseline, dict):
            continue
        agreement_eligible += 1
        if _agreement_for(parsed, baseline):
            agreement_count += 1

    scores: dict[str, float] = {
        "structured_output_validity_rate": rate(valid_count, len(records)),
        "agreement_with_baseline": rate(agreement_count, agreement_eligible),
    }
    logger.info(
        "[trading-eval json schema=%s] scores=%s n=%d valid=%d",
        schema.__name__, scores, len(records), valid_count,
    )
    return EvalResult(scores=scores, duration_seconds=0.0)


def _score_alias(*args: Any, **kwargs: Any) -> EvalResult:
    """Public scoring entrypoint. See module docstring."""
    return score(*args, **kwargs)


# Spec contract: the registry imports ``eval_structured_json.eval``.
globals()["eval"] = _score_alias


__all__ = [
    "score",
    "_score_alias",
    "_agreement_for",
    "_extract_json_blob",
]
