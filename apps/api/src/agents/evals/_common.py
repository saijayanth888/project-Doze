"""Shared helpers for the trading-eval modules.

These wrap three concerns each eval module needs:

1. **Test-set loading**  -- JSONL on disk -> list of dicts. Test sets are produced
   by the trading-bot exporter (one JSONL per role); the trading-bot side owns
   the schema, we just consume.
2. **Adapter inference**  -- batch-call the candidate adapter and return its raw
   text outputs. In production this hands off to ``peft_inference.run_with_adapter``;
   in tests it's injected so we can stay GPU-free.
3. **LLM-as-judge**  -- pairwise / rubric-score helper. Injectable for tests.

All public helpers accept callable hooks (``adapter_runner=`` and ``judge=``) so
the eval modules stay trivially mockable. The defaults route to the in-process
PEFT inference helper at import time only when ``MODELFORGE_EVAL_USE_PEFT=1``
to keep the test suite GPU-free.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

logger = logging.getLogger("modelforge.evals.common")

# Type aliases for the injectable hooks. Kept loose to avoid pinning callers
# to one concrete shape -- production wires in coroutines, tests wire in
# sync lambdas.
AdapterRunner = Callable[[str, list[str]], list[str]]
"""Signature: ``(adapter_path, prompts) -> responses``. Synchronous."""

Judge = Callable[[str, str, str], float]
"""Signature: ``(prompt, response_a, response_b) -> preference_score in [0,1]``.
Returns the probability response_a is preferred over response_b. 0.5 means tie.
"""

RubricScorer = Callable[[str, str, str], float]
"""Signature: ``(prompt, response, rubric) -> score in [0,1]`` (rescaled from 1-5)."""


# ---------------------------------------------------------------------
# Test-set loader
# ---------------------------------------------------------------------
def load_test_set(test_set_path: str | os.PathLike) -> list[dict[str, Any]]:
    """Load a JSONL test set from disk. One record per line.

    Returns an empty list with a warning when the path is missing or unreadable
    so the calling eval module produces an ``EvalResult`` with zero-confidence
    scores rather than crashing the whole evolution run.
    """
    p = Path(test_set_path)
    if not p.exists():
        logger.warning("[trading-eval] test set not found: %s", p)
        return []
    out: list[dict[str, Any]] = []
    try:
        with p.open("r", encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    out.append(json.loads(raw))
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "[trading-eval] skipping malformed line %d in %s: %s",
                        line_no, p, exc,
                    )
    except OSError as exc:
        logger.warning("[trading-eval] could not read test set %s: %s", p, exc)
        return []
    return out


# ---------------------------------------------------------------------
# Adapter inference
# ---------------------------------------------------------------------
def default_adapter_runner(adapter_path: str, prompts: list[str]) -> list[str]:
    """Production adapter runner -- thin wrapper over ``peft_inference``.

    Returns an empty-string response for every prompt when PEFT is not
    available (Mac dev, tests). Wired into modelforge's existing
    ``peft_inference.run_with_adapter_sync`` helper at runtime so the
    same warm-cache model serves both /api/forge/query and our evals.
    """
    use_peft = os.environ.get("MODELFORGE_EVAL_USE_PEFT", "").lower() in {"1", "true", "yes"}
    if not use_peft:
        return ["" for _ in prompts]
    try:
        # Lazy import -- peft_inference pulls torch which we want to avoid on Mac.
        from services import peft_inference  # type: ignore
    except ImportError as exc:
        logger.warning("[trading-eval] peft_inference unavailable, returning blanks: %s", exc)
        return ["" for _ in prompts]
    out: list[str] = []
    for prompt in prompts:
        try:
            resp = peft_inference.run_with_adapter_sync(
                adapter_path=adapter_path,
                prompt=prompt,
                max_new_tokens=512,
                temperature=0.0,
            )
            out.append(str(resp.get("response", "")) if isinstance(resp, dict) else str(resp))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[trading-eval] adapter inference failed: %s", exc)
            out.append("")
    return out


def default_judge(_prompt: str, _resp_a: str, _resp_b: str) -> float:
    """Tie-by-default judge. Production overrides with an Ollama hermes3:8b call."""
    return 0.5


def default_rubric_scorer(_prompt: str, _response: str, _rubric: str) -> float:
    """Conservative 0.5 baseline when no real judge is wired in."""
    return 0.5


# ---------------------------------------------------------------------
# Numeric / citation helpers (used by reflector + debaters)
# ---------------------------------------------------------------------
# Capture the optional sign whether it appears before or after the $. So both
# "-$120.0" and "$-120.0" yield the same numeric value, matching how humans
# tend to write losses in trading prose.
_DOLLAR_RE = re.compile(r"(?P<lead>[-+]?)\$(?P<inner>[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?)")
_PERCENT_RE = re.compile(r"[-+]?\d+(?:\.\d+)?\s*%")
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?)?\b")
_TICKER_RE = re.compile(r"\b[A-Z]{1,5}(?:\.[A-Z])?\b")

# Common technical indicator names trading-bot mentions in prose.
_INDICATOR_TOKENS = (
    "RSI", "MACD", "EMA", "SMA", "BBANDS", "BB", "VWAP", "ATR",
    "ADX", "OBV", "STOCH", "ICHIMOKU", "SUPERTREND", "MFI",
)


def count_evidence_tokens(text: str) -> dict[str, int]:
    """Count dollar-prices, percent-moves, ISO dates, indicator names in ``text``.

    Used by the bull/bear evidence-density score. Returns a dict instead of a
    single number so the eval can weight by token type if needed later.
    """
    if not isinstance(text, str) or not text:
        return {"dollars": 0, "percents": 0, "dates": 0, "indicators": 0}
    return {
        "dollars": len(_DOLLAR_RE.findall(text)),
        "percents": len(_PERCENT_RE.findall(text)),
        "dates": len(_ISO_DATE_RE.findall(text)),
        "indicators": sum(text.upper().count(tok) for tok in _INDICATOR_TOKENS),
    }


def extract_first_dollar_value(text: str) -> float | None:
    """Pull the first ``$N`` figure from text as a float. None if absent.

    Handles both ``-$120.0`` and ``$-120.0`` -- whichever side carries the
    sign, the returned value is negative. Used by the reflector faithfulness
    check: the gold-truth trade row carries the realized alpha figure and we
    check whether the model cited it.
    """
    if not isinstance(text, str):
        return None
    m = _DOLLAR_RE.search(text)
    if not m:
        return None
    lead = m.group("lead") or ""
    inner = (m.group("inner") or "").replace(",", "")
    if not inner:
        return None
    try:
        value = float(inner)
    except ValueError:
        return None
    # If the leading sign is "-" and the inner number is positive, negate.
    if lead == "-" and value > 0:
        value = -value
    return value


def values_match_to_decimal(a: float | None, b: float | None, decimals: int = 1) -> bool:
    """True when ``a`` and ``b`` agree at ``decimals`` places. ``None`` -> False."""
    if a is None or b is None:
        return False
    factor = 10 ** decimals
    return round(a * factor) == round(b * factor)


def mentions_token(text: str, token: str) -> bool:
    """Case-insensitive substring presence check. Empty token / text -> False."""
    if not text or not token:
        return False
    return token.lower() in text.lower()


# ---------------------------------------------------------------------
# Score-bookkeeping helpers
# ---------------------------------------------------------------------
def clamp01(x: float) -> float:
    """Pin ``x`` to ``[0.0, 1.0]``. Useful for evidence-density normalization."""
    if x != x:  # NaN
        return 0.0
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return float(x)


def rate(numerator: int, denominator: int) -> float:
    """Safe division: returns 0.0 when ``denominator`` is 0."""
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def mean(values: Iterable[float]) -> float:
    """Arithmetic mean, returning 0.0 for empty iterables."""
    vals = [float(v) for v in values]
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


__all__ = [
    "AdapterRunner",
    "Judge",
    "RubricScorer",
    "clamp01",
    "count_evidence_tokens",
    "default_adapter_runner",
    "default_judge",
    "default_rubric_scorer",
    "extract_first_dollar_value",
    "load_test_set",
    "mean",
    "mentions_token",
    "rate",
    "values_match_to_decimal",
]
