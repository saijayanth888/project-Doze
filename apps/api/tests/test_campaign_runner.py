"""Smoke tests for the CampaignRunner state machine and exp dispatch.

Heavy IO (real evaluations / DB writes) is mocked — we're testing the
state machine wiring, not the underlying agents.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.campaign_runner import CampaignRunner, get_campaign_runner


def test_singleton_is_stable():
    a = get_campaign_runner()
    b = get_campaign_runner()
    assert a is b


def test_initial_status():
    r = CampaignRunner()
    s = r.get_status()
    assert s["status"] == "idle"
    assert s["completed"] == 0
    assert s["failed"] == 0


def test_pause_resume_stop_no_op_when_idle():
    r = CampaignRunner()
    r.pause()
    assert r.status == "idle"
    r.resume()
    assert r.status == "idle"
    r.stop()
    assert r.status == "idle"


def test_state_transitions_running_to_paused_to_running():
    r = CampaignRunner()
    r.status = "running"
    r.pause()
    assert r.status == "paused"
    r.resume()
    assert r.status == "running"
    r.stop()
    assert r.status == "stopping"


def test_eval_only_experiment_uses_eval_backend(monkeypatch):
    r = CampaignRunner()

    fake_eval = AsyncMock()
    fake_eval.return_value = MagicMock(
        scores={"mmlu": 0.5, "gsm8k": 0.4},
        duration_seconds=12.3,
        harness_version="0.4.x",
        stderrs={},
    )

    class _FakeBackend:
        def __init__(self):
            pass

        async def evaluate(self, **kwargs):
            return await fake_eval(**kwargs)

    monkeypatch.setattr(
        "agents.eval_backend.LMEvalHarnessBackend", _FakeBackend
    )

    result = asyncio.run(
        r._run_single_experiment(  # type: ignore[attr-defined]
            {"eval_only": True, "model": "test/model"}, db=None, idx=0,
        )
    )
    assert result["method"] == "baseline"
    assert result["scores"] == {"mmlu": 0.5, "gsm8k": 0.4}
    assert result["avg_score"] == pytest.approx(0.45)


def test_start_rejects_double_start():
    r = CampaignRunner()
    r.status = "running"

    async def _run():
        with pytest.raises(ValueError):
            await r.start("plan-x", [{"eval_only": True, "model": "test/model"}], db=None)

    asyncio.run(_run())
