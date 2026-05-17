"""Tests for the real Ollama judge + rubric scorer + GPU-gated adapter runner.

Section J tests 1-8 from spec 2026-05-17-trading-data-pipeline-rebuild.md.

Tests 2, 3, 6, 8 require Ollama to be reachable. They are gated by
OLLAMA_AVAILABLE / GPU_AVAILABLE markers and skipped in environments where
those resources are absent. Tests 1, 4, 5, 7 run everywhere.

No GPU / no torch needed for the core unit tests — the adapter runner
non-GPU path is the expected behavior in test environments.
"""

from __future__ import annotations

import os
import unittest

import pytest

# ---------------------------------------------------------------------------
# Availability probes (evaluated at module load, not per-test, so the skip
# messages are consistent and collection is fast)
# ---------------------------------------------------------------------------

def _ollama_available() -> bool:
    """Return True when the Ollama host is reachable."""
    try:
        import httpx
        from config.settings import settings
        r = httpx.get(
            f"{settings.ollama_host.rstrip('/')}/api/tags",
            timeout=3.0,
        )
        return r.status_code == 200
    except Exception:
        return False


def _gpu_available() -> bool:
    """Return True when the host reports a GPU."""
    try:
        from utils.gpu import get_gpu_status
        return bool(get_gpu_status().get("gpu_available"))
    except Exception:
        return False


OLLAMA_AVAILABLE = _ollama_available()
GPU_AVAILABLE = _gpu_available()

requires_ollama = pytest.mark.skipif(
    not OLLAMA_AVAILABLE,
    reason="Ollama not reachable — skip live judge tests",
)
requires_gpu = pytest.mark.skipif(
    not GPU_AVAILABLE,
    reason="GPU not available — skip GPU adapter runner tests",
)


# ---------------------------------------------------------------------------
# Test 1: default_judge returns 0.5 when Ollama is unreachable
# ---------------------------------------------------------------------------
def test_default_judge_stub_returns_0_5(monkeypatch):
    """When Ollama is unreachable, judge falls back to 0.5 and logs ERROR."""
    import httpx
    from agents.evals._common import default_judge

    def _raise(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "Client", lambda **kw: _MockHTTPCtx(_raise))
    result = default_judge("describe a trade", "response A", "response B")
    assert result == pytest.approx(0.5), f"Expected 0.5 fallback, got {result}"


class _MockHTTPCtx:
    """Minimal context manager for monkeypatching httpx.Client."""
    def __init__(self, side_effect):
        self._side_effect = side_effect

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def post(self, *args, **kwargs):
        self._side_effect(*args, **kwargs)


# ---------------------------------------------------------------------------
# Test 2: default_judge returns float in [0,1] with real Ollama
# ---------------------------------------------------------------------------
@requires_ollama
def test_default_judge_real_ollama():
    """With real Ollama, judge returns a float in [0, 1]."""
    from agents.evals._common import default_judge
    score = default_judge(
        "Should we buy AAPL given the current market conditions?",
        "AAPL shows strong technicals with RSI at 45 and MACD crossover above the signal line. "
        "Q2 earnings beat by 12%. Buy.",
        "The market looks okay I guess.",
    )
    assert isinstance(score, float), f"Expected float, got {type(score)}"
    assert 0.0 <= score <= 1.0, f"Score {score} outside [0,1]"


# ---------------------------------------------------------------------------
# Test 3: default_judge discriminates — better response gets score > 0.6
# ---------------------------------------------------------------------------
@requires_ollama
def test_default_judge_discriminates():
    """Judge assigns score_a > 0.6 for a clearly better trading response.

    This test catches stub-like judges that always return ~0.5. If the judge
    cannot discriminate between an empty/incoherent response and a specific,
    evidence-dense response, eval metrics are theatrical.
    """
    from agents.evals._common import default_judge

    good_response = (
        "Buy AAPL. Q2 earnings beat by 12%, technical breakout above 200-day moving average "
        "at $185.20, sector rotating into technology. RSI at 58 — not overbought. "
        "Risk: Fed meeting Thursday could reverse the move. Stop at $181."
    )
    bad_response = "idk, looks ok i guess, maybe buy"

    prompt = "Should we enter AAPL today given the current market conditions?"
    score = default_judge(prompt, good_response, bad_response)

    assert score > 0.6, (
        f"Judge should prefer the evidence-dense response (score_a > 0.6), "
        f"but got score_a={score:.3f}. "
        f"This indicates the judge is stub-like (always ~0.5)."
    )


# ---------------------------------------------------------------------------
# Test 4: default_judge refuses same-family model
# ---------------------------------------------------------------------------
def test_default_judge_refuses_same_family(monkeypatch):
    """ValueError raised when MODELFORGE_JUDGE_MODEL starts with hermes3."""
    monkeypatch.setenv("MODELFORGE_JUDGE_MODEL", "hermes3:8b")
    from agents.evals import _common
    # Reimport to pick up the env var — the function reads it at call time.
    import importlib
    importlib.reload(_common)
    with pytest.raises(ValueError, match="same family"):
        _common.default_judge("test prompt", "response a", "response b")


# ---------------------------------------------------------------------------
# Test 5: default_adapter_runner returns empty strings when GPU absent
# ---------------------------------------------------------------------------
def test_default_adapter_runner_no_gpu_returns_empty(monkeypatch):
    """On a non-GPU host, default_adapter_runner returns '' for every prompt."""
    from utils import gpu as gpu_module

    monkeypatch.setattr(gpu_module, "get_gpu_status", lambda: {"gpu_available": False})
    from agents.evals._common import default_adapter_runner
    prompts = ["prompt one", "prompt two", "prompt three"]
    results = default_adapter_runner("some/adapter/path", prompts)
    assert results == ["", "", ""], f"Expected all-empty list, got {results}"
    assert len(results) == len(prompts)


# ---------------------------------------------------------------------------
# Test 6: default_adapter_runner calls peft_inference on GPU host
# ---------------------------------------------------------------------------
@requires_gpu
def test_default_adapter_runner_gpu_calls_peft(monkeypatch, tmp_path):
    """On a GPU host, adapter runner calls peft_inference.run_with_adapter_sync."""
    call_log: list[dict] = []

    class _MockPeftInference:
        @staticmethod
        def run_with_adapter_sync(adapter_path, prompt, max_new_tokens, temperature):
            call_log.append({"adapter_path": adapter_path, "prompt": prompt})
            return {"response": f"mock_response_for: {prompt[:20]}"}

    import services
    monkeypatch.setattr(services, "peft_inference", _MockPeftInference(), raising=False)

    from agents.evals._common import default_adapter_runner
    results = default_adapter_runner("mock/adapter", ["test prompt"])
    assert len(results) == 1
    assert "mock_response_for" in results[0]
    assert len(call_log) == 1
    assert call_log[0]["adapter_path"] == "mock/adapter"


# ---------------------------------------------------------------------------
# Test 7: default_rubric_scorer rescales 1-5 to [0,1]
# ---------------------------------------------------------------------------
def test_rubric_scorer_parses_1_to_5_scale(monkeypatch):
    """Rubric scorer correctly rescales: score=3 → 0.5, score=5 → 1.0, score=1 → 0.0."""
    import httpx

    # Patch httpx.Client to return different scores on each call
    scores_to_return = iter([3, 5, 1])

    class _MockResponse:
        def json(self):
            score = next(scores_to_return)
            return {"response": f'{{"score": {score}, "reason": "test"}}'}

    class _MockClient:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, *a, **kw): return _MockResponse()

    monkeypatch.setattr(httpx, "Client", lambda **kw: _MockClient())

    from agents.evals._common import default_rubric_scorer
    rubric = "1=bad, 3=ok, 5=excellent"

    r3 = default_rubric_scorer("prompt", "response", rubric)
    assert r3 == pytest.approx(0.5), f"score=3 should rescale to 0.5, got {r3}"

    r5 = default_rubric_scorer("prompt", "response", rubric)
    assert r5 == pytest.approx(1.0), f"score=5 should rescale to 1.0, got {r5}"

    r1 = default_rubric_scorer("prompt", "response", rubric)
    assert r1 == pytest.approx(0.0), f"score=1 should rescale to 0.0, got {r1}"


# ---------------------------------------------------------------------------
# Test 8: default_rubric_scorer discriminates between quality responses
# ---------------------------------------------------------------------------
@requires_ollama
def test_rubric_scorer_discriminates():
    """Rubric scorer assigns a higher score to a clearly better trading response.

    This catches stub-like scorers that always return 0.5.
    """
    from agents.evals._common import default_rubric_scorer

    rubric = (
        "Score 1-5: 1=incoherent, 2=vague, 3=acceptable, "
        "4=specific and causal, 5=insightful + actionable. "
        "Reward citing exact figures, entry/exit timing, and at least one indicator."
    )

    good_response = (
        "Closed AAPL long at $187.40 (entry $181.20), +$6.20 (+3.4%). "
        "The thesis of a post-earnings MACD crossover above the 50-day EMA played out. "
        "RSI peaked at 72 — we should have tightened the stop at 70. "
        "Lesson: trail the stop 0.5 ATR above entry after RSI > 68."
    )

    bad_response = "trade went ok I think, we made some money, not sure about the details"

    rubric_prompt = "Summarize this closed trade and extract a lesson."
    score_good = default_rubric_scorer(rubric_prompt, good_response, rubric)
    score_bad = default_rubric_scorer(rubric_prompt, bad_response, rubric)

    assert score_good > score_bad, (
        f"Good response (score={score_good:.3f}) should outscore bad response "
        f"(score={score_bad:.3f}). Rubric scorer is stub-like if this fails."
    )
    # The good response should score at least 0.55 (3/5 or better).
    assert score_good >= 0.5, (
        f"Good response got score={score_good:.3f} < 0.5; "
        f"rubric scorer may be broken or Ollama returned garbage."
    )
