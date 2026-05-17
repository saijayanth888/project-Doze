"""Shared helpers for the trading-eval modules.

These wrap three concerns each eval module needs:

1. **Test-set loading**  -- JSONL on disk -> list of dicts. Test sets are produced
   by the trading-bot exporter (one JSONL per role); the trading-bot side owns
   the schema, we just consume.
2. **Adapter inference**  -- batch-call the candidate adapter and return its raw
   text outputs. In production this hands off to ``peft_inference.run_with_adapter``
   on GPU hosts. On CPU-only hosts the runner returns empty strings so that
   tests can inject their own runner without depending on GPU presence.
3. **LLM-as-judge**  -- pairwise / rubric-score helper backed by a DIFFERENT
   model family than the student (qwen3:8b default) to avoid same-author bias.
   Injectable for tests.

MODELFORGE_EVAL_USE_PEFT has been removed. GPU-presence detection via
``utils.gpu.get_gpu_status()`` drives the adapter runner instead.
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
    """Production adapter runner — GPU-gated, no env-var toggle.

    On CPU-only hosts (test environments, Mac dev): returns empty strings for
    every prompt. Tests MUST inject their own ``adapter_runner=`` lambda;
    no test should rely on this function producing real output on a GPU-absent
    host.

    On GPU hosts: imports and calls ``services.peft_inference.run_with_adapter_sync``.
    Raises ``RuntimeError`` if peft_inference is missing on a GPU host — that
    is a misconfigured deployment, not a graceful degradation case.

    The ``MODELFORGE_EVAL_USE_PEFT`` env var has been removed. GPU detection
    is the sole gate.
    """
    from utils.gpu import get_gpu_status
    if not get_gpu_status().get("gpu_available"):
        # Non-GPU env: tests must inject their own runner.
        return ["" for _ in prompts]
    try:
        from services import peft_inference  # type: ignore
    except ImportError as exc:
        logger.error("[trading-eval] peft_inference unavailable on GPU host: %s", exc)
        raise RuntimeError("GPU host must have peft_inference installed") from exc
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


def default_judge(prompt: str, resp_a: str, resp_b: str) -> float:
    """Real Ollama judge from a DIFFERENT model family than the student.

    The student is hermes3:8b + LoRA. This judge uses qwen3:8b (different
    family) by default to avoid same-author evaluation bias. Falls back to
    0.5 on failure but logs an ERROR.

    Override the judge model via ``MODELFORGE_JUDGE_MODEL`` env var. Setting
    it to any hermes3:* value raises ``ValueError`` (same-family guard).

    Validated for discriminative capacity in test_default_judge_discriminates.
    """
    import httpx
    from config.settings import settings

    judge_model = os.environ.get("MODELFORGE_JUDGE_MODEL", "qwen3:8b")
    if judge_model.startswith("hermes3"):
        raise ValueError(
            f"MODELFORGE_JUDGE_MODEL={judge_model!r} is same family as student (hermes3); "
            "choose a different model family (qwen3, phi3.5, mistral)."
        )

    judge_prompt = (
        f"Prompt given to the analyst:\n{prompt[:800]}\n\n"
        f"Response A:\n{resp_a[:600]}\n\nResponse B:\n{resp_b[:600]}\n\n"
        'Which response is better for a trading decision? Reply ONLY with a JSON object: '
        '{"preference": "A" or "B" or "tie", "score_a": 0.0-1.0, "score_b": 0.0-1.0, "reason": "..."}'
    )
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.post(
                f"{settings.ollama_host.rstrip('/')}/api/generate",
                json={"model": judge_model, "prompt": judge_prompt, "stream": False},
            )
        blob = r.json().get("response", "")
        m = re.search(r"\{.*\}", blob, re.DOTALL)
        if m:
            parsed = json.loads(m.group(0))
            return float(parsed.get("score_a", 0.5))
    except Exception as exc:
        logger.warning("[trading-eval] judge call failed (%s): %s", judge_model, exc)
    return 0.5


def default_rubric_scorer(prompt: str, response: str, rubric: str) -> float:
    """Real Ollama rubric scorer using the same judge model as default_judge.

    Sends a 1-5 rubric prompt and rescales to [0, 1] via ``(raw - 1) / 4``.
    On any failure, returns 0.5 (not 0.0) to avoid false metric collapse
    due to transient Ollama unavailability.
    """
    import httpx
    from config.settings import settings

    judge_model = os.environ.get("MODELFORGE_JUDGE_MODEL", "qwen3:8b")
    if judge_model.startswith("hermes3"):
        raise ValueError(
            f"MODELFORGE_JUDGE_MODEL={judge_model!r} is same family as student; "
            "choose a different model family."
        )

    rubric_prompt = (
        f"Rubric:\n{rubric}\n\n"
        f"Prompt given to the analyst:\n{prompt[:600]}\n\n"
        f"Response:\n{response[:800]}\n\n"
        'Score this response 1-5 per the rubric above. '
        'Reply ONLY with a JSON object: {"score": 1-5, "reason": "brief explanation"}'
    )
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.post(
                f"{settings.ollama_host.rstrip('/')}/api/generate",
                json={"model": judge_model, "prompt": rubric_prompt, "stream": False},
            )
        blob = r.json().get("response", "")
        m = re.search(r"\{.*\}", blob, re.DOTALL)
        if m:
            parsed = json.loads(m.group(0))
            raw = float(parsed.get("score", 3.0))
            # Rescale 1-5 to [0, 1]
            return clamp01((raw - 1.0) / 4.0)
    except Exception as exc:
        logger.error("[trading-eval] rubric_scorer call failed (%s): %s", judge_model, exc)
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
