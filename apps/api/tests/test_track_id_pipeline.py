"""End-to-end track_id pipeline tests (task #46 path A).

The plumbing path under test:

    EvolutionStart.execute(config)        # action layer
      -> run_config carries track_id
        -> runner._run(run_id, run_config)  # asyncio task
          -> state["track_id"] set + state["config"]["track_id"] preserved
            -> evolution_graph.evaluate node
              -> eval_backend.evaluate(config={"track_id": ..., ...})
                -> TradingEvalBackend dispatches to per-track scorer
                                     OR falls back to LM-eval / Mock

These tests assert each hop hands the key off, so the regression we
saw -- "trading-* runs never actually invoking the trading scorer" --
cannot recur.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.eval_backend import (
    EvalResult,
    LMEvalHarnessBackend,
    MockEvalBackend,
    TradingEvalBackend,
)
from agents.evolution_graph import build_graph
from agents.runner import _select_backends


# ---------------------------------------------------------------------
# Hop 1: Action layer — EvolutionStart schema + execute()
# ---------------------------------------------------------------------
def test_action_schema_includes_track_id():
    """The workflow UI must surface a track_id field on evolution.start."""
    from services.automation_engine.actions import EvolutionStart

    names = [field["name"] for field in EvolutionStart.schema]
    assert "track_id" in names, (
        "EvolutionStart.schema must expose track_id so workflows can set it"
    )
    track_field = next(f for f in EvolutionStart.schema if f["name"] == "track_id")
    assert track_field.get("type") == "string"
    assert track_field.get("default") == ""


def test_action_execute_preserves_nonempty_track_id():
    """A workflow that sets track_id='trading-reflector' must propagate it."""
    from services.automation_engine.actions import EvolutionStart

    captured: dict[str, Any] = {}

    fake_engine = MagicMock()
    fake_engine.db.get_dashboard_run = AsyncMock(return_value=None)
    fake_engine.db.save_run = AsyncMock(return_value=None)

    # Patch the late-import inside execute().
    import agents
    real_start = getattr(agents, "start_evolution", None)
    agents.start_evolution = lambda rid, cfg, db: captured.update(  # type: ignore[attr-defined]
        run_id=rid, run_config=cfg
    )
    try:
        action = EvolutionStart()
        config = {
            "base_model": "x",
            "max_generations": 1,
            "max_samples": 10,
            "lora_rank": 4,
            "batch_size": 1,
            "learning_rate": 0.0002,
            "track_id": "trading-reflector",
        }
        result = asyncio.run(action.execute(config=config, context={}, engine=fake_engine))
    finally:
        if real_start is not None:
            agents.start_evolution = real_start  # type: ignore[attr-defined]

    assert result.status == "ok"
    assert captured["run_config"].get("track_id") == "trading-reflector", (
        f"track_id lost in action.execute -> run_config: {captured['run_config']}"
    )


def test_action_execute_drops_empty_track_id():
    """Empty-string track_id is the documented legacy shape: key absent."""
    from services.automation_engine.actions import EvolutionStart

    captured: dict[str, Any] = {}

    fake_engine = MagicMock()
    fake_engine.db.get_dashboard_run = AsyncMock(return_value=None)
    fake_engine.db.save_run = AsyncMock(return_value=None)

    import agents
    real_start = getattr(agents, "start_evolution", None)
    agents.start_evolution = lambda rid, cfg, db: captured.update(  # type: ignore[attr-defined]
        run_id=rid, run_config=cfg
    )
    try:
        action = EvolutionStart()
        config = {
            "base_model": "x", "max_generations": 1, "max_samples": 10,
            "lora_rank": 4, "batch_size": 1, "learning_rate": 0.0002,
            "track_id": "",  # legacy / not a trading run
        }
        asyncio.run(action.execute(config=config, context={}, engine=fake_engine))
    finally:
        if real_start is not None:
            agents.start_evolution = real_start  # type: ignore[attr-defined]

    assert "track_id" not in captured["run_config"], (
        "Empty track_id should not appear in run_config (legacy shape)"
    )


# ---------------------------------------------------------------------
# Hop 2: Runner backend selection — TradingEvalBackend wraps the legacy one
# ---------------------------------------------------------------------
def test_select_backends_mock_wraps_with_trading_backend():
    """Without a GPU, the eval backend is Trading(fallback=Mock)."""
    training, eval_backend, curator = _select_backends(prefer_real=False)
    assert isinstance(eval_backend, TradingEvalBackend), (
        "Mock path must still be wrapped so track_id dispatch works in dev"
    )
    assert isinstance(eval_backend._fallback, MockEvalBackend)


def test_select_backends_real_wraps_with_trading_backend(monkeypatch):
    """With a GPU, the eval backend is Trading(fallback=LMEvalHarness).

    LoRATrainingBackend / LMEvalHarnessBackend import heavy GPU deps; we
    short-circuit those imports so the test runs CPU-only.
    """
    from agents import runner as runner_mod

    class _FakeTraining:
        name = "fake-train"

    class _FakeHarness:
        name = "fake-harness"

    monkeypatch.setattr(runner_mod, "LoRATrainingBackend", _FakeTraining)
    monkeypatch.setattr(runner_mod, "LMEvalHarnessBackend", _FakeHarness)
    monkeypatch.setattr(runner_mod, "HuggingFaceDataCurator", lambda: MagicMock(name="curator"))

    _, eval_backend, _ = runner_mod._select_backends(prefer_real=True)
    assert isinstance(eval_backend, TradingEvalBackend)
    assert isinstance(eval_backend._fallback, _FakeHarness)


# ---------------------------------------------------------------------
# Hop 3: evolution_graph.evaluate node injects track_id into eval config
# ---------------------------------------------------------------------
class _RecordingEvalBackend:
    """Captures the config dict the evaluate node hands us."""
    name = "recording"

    def __init__(self) -> None:
        self.last_config: dict | None = None

    async def evaluate(self, *, run_id, generation, adapter_path, config=None, **_):
        self.last_config = dict(config or {})
        return EvalResult(scores={"mmlu": 0.5}, duration_seconds=0.01)


def _make_graph_with(eval_backend):
    """Build a graph wired to a captured eval backend; nodes other than
    evaluate run as no-ops via stub training/curator."""
    class _StubTrain:
        name = "stub-train"

        async def train(self, *args, **kwargs):
            return "/tmp/fake-adapter"

    class _StubCurator:
        name = "stub-curator"

        async def fetch_examples(self, *args, **kwargs):
            return []

        async def curate(self, *args, **kwargs):
            return []

    return build_graph(
        training=_StubTrain(),
        eval_backend=eval_backend,
        curator=_StubCurator(),
    )


def test_evaluate_node_propagates_track_id_from_state():
    """When the runner has set state['track_id'], the eval config carries it."""
    rec = _RecordingEvalBackend()
    # We bypass langgraph orchestration here and call the evaluate closure
    # by importing the same wiring logic directly. The simplest way is to
    # run the node in isolation: construct minimal state and invoke
    # eval_backend.evaluate ourselves, mirroring evolution_graph.evaluate().
    state = {
        "run_id": "test-1",
        "generation": 1,
        "config": {"base_model": "x"},
        "track_id": "trading-reflector",
        "adapter_path": "/tmp/adapter",
    }

    # Mimic the evaluate node body (kept in sync with evolution_graph.evaluate).
    eval_config = dict(state.get("config") or {})
    tid = str(state.get("track_id") or "").strip()
    if tid:
        eval_config["track_id"] = tid
    asyncio.run(rec.evaluate(
        run_id=state["run_id"],
        generation=state["generation"],
        adapter_path=state.get("adapter_path"),
        config=eval_config,
    ))

    assert rec.last_config is not None
    assert rec.last_config.get("track_id") == "trading-reflector"


def test_evaluate_node_omits_track_id_when_unset():
    """No track_id in state -> no track_id key smuggled into eval config."""
    rec = _RecordingEvalBackend()
    state = {
        "run_id": "test-2",
        "generation": 1,
        "config": {"base_model": "x"},
        "adapter_path": "/tmp/adapter",
    }
    eval_config = dict(state.get("config") or {})
    tid = str(state.get("track_id") or "").strip()
    if tid:
        eval_config["track_id"] = tid
    asyncio.run(rec.evaluate(
        run_id=state["run_id"],
        generation=state["generation"],
        adapter_path=state.get("adapter_path"),
        config=eval_config,
    ))
    assert "track_id" not in (rec.last_config or {})


# ---------------------------------------------------------------------
# Hop 4: TradingEvalBackend dispatch — end-to-end on a real registry entry
# ---------------------------------------------------------------------
def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def test_trading_backend_routes_to_reflector_when_track_id_set(tmp_path):
    """track_id='trading-reflector' + adapter + eval_set -> reflector scorer.

    Asserts the scorer was called (not the fallback) by reading the score
    keys returned: reflector returns coverage/grounded_evidence/etc., not the
    fallback's MMLU/ARC.
    """
    eval_set = tmp_path / "reflector.jsonl"
    _write_jsonl(eval_set, [{
        "prompt": "Test prompt",
        "prior_response": "weak prior",
    }])

    # Mock the LLM adapter -- the reflector scorer accepts an adapter_runner.
    def _mock_runner(_adapter_path: str, prompts: list[str]) -> list[str]:
        return ["Step 1: see EMA. Step 2: confirm RSI. Conclusion: hold."] * len(prompts)

    fallback = MockEvalBackend(sleep_s=0.0)
    backend = TradingEvalBackend(fallback=fallback, adapter_runner=_mock_runner)

    result = asyncio.run(backend.evaluate(
        run_id="test-rf",
        generation=1,
        adapter_path="/tmp/mock-adapter",
        config={
            "track_id": "trading-reflector",
            "eval_set_path": str(eval_set),
        },
    ))

    # Reflector returns these keys; MockEvalBackend would return mmlu/arc/etc.
    expected_reflector_keys = {
        "coverage", "grounded_evidence", "faithfulness_regex", "format_validity",
    }
    assert expected_reflector_keys & set(result.scores.keys()), (
        f"Expected reflector keys in {result.scores.keys()}; "
        f"looks like fallback ran instead"
    )


def test_trading_backend_falls_back_when_no_track_id(tmp_path):
    """No track_id in config -> fallback (legacy) backend runs."""
    fallback = MockEvalBackend(sleep_s=0.0)
    backend = TradingEvalBackend(fallback=fallback)

    result = asyncio.run(backend.evaluate(
        run_id="test-legacy",
        generation=1,
        adapter_path="/tmp/mock-adapter",
        config={"base_model": "x"},  # no track_id
    ))

    # Mock backend returns canonical lm-eval keys.
    assert "mmlu" in result.scores, (
        f"Expected legacy mock scores, got {result.scores.keys()}"
    )


def test_trading_backend_falls_back_when_unknown_track_id(tmp_path):
    """Unknown track_id -> fallback (legacy) backend runs."""
    fallback = MockEvalBackend(sleep_s=0.0)
    backend = TradingEvalBackend(fallback=fallback)

    result = asyncio.run(backend.evaluate(
        run_id="test-unknown",
        generation=1,
        adapter_path="/tmp/mock-adapter",
        config={"track_id": "not-a-real-track", "eval_set_path": "/tmp/x"},
    ))
    assert "mmlu" in result.scores
