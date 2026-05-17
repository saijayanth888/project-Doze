"""Pin down the RAM precheck on the evolution.start action.

Added 2026-05-17 after qwen3:30b OOM-killed every Trading-LoRA training
run on a 121 GB unified-memory host. The precheck refuses to start a run
when the fp16 base model + LoRA training overhead can't fit in free RAM.
Without this guard, the worker downloads ~60 GB from HuggingFace before
getting SIGKILL'd, wasting bandwidth and host stability.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from services.automation_engine.actions import (
    _check_ram_for_base_model,
    _estimate_params_billions,
)


# ── parameter-count extraction ────────────────────────────────────────


@pytest.mark.parametrize("name,expected", [
    # Clear "<N>B" tokens — the common case.
    ("Qwen/Qwen3-30B-A3B-Instruct-2507", 30.0),
    ("qwen3:30b", 30.0),
    ("NousResearch/Hermes-3-Llama-3.1-8B", 8.0),
    ("hermes3:8b", 8.0),
    ("hermes3:70b", 70.0),
    ("llama3.1:8b", 8.0),
    # No <N>B token — conservative 8B fallback.
    ("", 8.0),
    ("no-size-in-name", 8.0),
    ("microsoft/Phi-3.5-mini-instruct", 8.0),
])
def test_estimate_params_billions_extracts_b_token(name, expected):
    """The estimator picks the largest "<N>B" token. Models that don't
    encode size in the name (e.g. Phi-3.5-mini) fall back to a
    conservative 8B."""
    assert _estimate_params_billions(name) == expected


def test_decimal_dotted_size_token():
    """Bonus: 3.5B should parse to 3.5 (matches the float regex). We
    don't have any such model in production today but the regex supports
    it for forward-compat with future repos."""
    assert _estimate_params_billions("phi-3.5B-something") == 3.5


# ── happy path — sufficient RAM allows the run ────────────────────────


def test_precheck_allows_8b_model_on_plentiful_ram():
    """76 GB free comfortably hosts an 8B model's LoRA training."""
    fake_mem = type("M", (), {"available": 76 * 1024**3})()
    with patch("psutil.virtual_memory", return_value=fake_mem):
        result = _check_ram_for_base_model("NousResearch/Hermes-3-Llama-3.1-8B")
    assert result is None  # None = allow


def test_precheck_allows_3b_model_on_plentiful_ram():
    fake_mem = type("M", (), {"available": 60 * 1024**3})()
    with patch("psutil.virtual_memory", return_value=fake_mem):
        result = _check_ram_for_base_model("meta-llama/Llama-3.2-3B")
    assert result is None


# ── failure path — 30B refused on a host that's already half-full ────


def test_precheck_blocks_30b_on_typical_host():
    """The 2026-05-17 failure mode: 30B base model on 76 GB free RAM.
    Required = 30 * 2 * 1.3 + 10 = 88 GB > 76. Must refuse."""
    fake_mem = type("M", (), {"available": 76 * 1024**3})()
    with patch("psutil.virtual_memory", return_value=fake_mem):
        result = _check_ram_for_base_model("Qwen/Qwen3-30B-A3B-Instruct-2507")
    assert result is not None
    assert result.status == "error"
    assert result.error == "insufficient_ram"
    assert "30B" in result.message or "30" in result.message
    # Output dict carries machine-readable numbers for monitoring.
    assert result.output["params_billions"] == 30.0
    assert result.output["free_gb"] == 76.0
    assert result.output["required_gb"] == 88.0


def test_precheck_blocks_70b_on_any_realistic_host():
    """70B requires 70 * 2 * 1.3 + 10 = 192 GB — refuses even with 100 GB free."""
    fake_mem = type("M", (), {"available": 100 * 1024**3})()
    with patch("psutil.virtual_memory", return_value=fake_mem):
        result = _check_ram_for_base_model("hermes3:70b")
    assert result is not None
    assert result.status == "error"


# ── env override path — operator can opt out for experiments ─────────


def test_precheck_respects_disable_env(monkeypatch):
    """MODELFORGE_RAM_PRECHECK=0 short-circuits — used for one-off
    experiments when the operator knows what they're doing."""
    monkeypatch.setenv("MODELFORGE_RAM_PRECHECK", "0")
    fake_mem = type("M", (), {"available": 1 * 1024**3})()  # 1 GB free
    with patch("psutil.virtual_memory", return_value=fake_mem):
        result = _check_ram_for_base_model("hermes3:70b")
    assert result is None  # Override → no block


# ── psutil-unavailable path — don't block the whole pipeline ─────────


def test_precheck_skipped_when_psutil_unavailable(caplog):
    """If psutil can't be imported (shouldn't happen but guard for it),
    log + allow rather than block. Better an OOM that the operator can
    see than a silent permanent refusal."""
    with patch("psutil.virtual_memory", side_effect=Exception("simulated")):
        result = _check_ram_for_base_model("hermes3:8b")
    assert result is None
