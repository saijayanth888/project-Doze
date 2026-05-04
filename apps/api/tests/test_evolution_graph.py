"""Evolution graph happy path with mock backends."""

from __future__ import annotations

from typing import Any

import pytest

from agents.eval_backend import MockEvalBackend
from agents.evolution_graph import build_graph
from agents.training_backend import MockTrainingBackend
from services.data_curator import MockDataCurator


@pytest.mark.asyncio
async def test_graph_runs_to_max_generations():
    states: list[tuple[str, int, str]] = []

    async def cb(state: Any, step: str) -> None:
        states.append((step, state.get("generation"), state.get("decision")))

    graph = build_graph(
        training=MockTrainingBackend(0.0),
        eval_backend=MockEvalBackend(0.0),
        curator=MockDataCurator(),
        on_state_change=cb,
    )

    final = await graph.ainvoke(
        {
            "run_id": "test",
            "config": {"max_generations": 4},
            "generation": 0,
            "max_generations": 4,
            "parent_scores": {},
            "child_scores": {},
            "decision": "",
            "decision_reason": "",
            "method": "",
            "adapter_path": None,
            "training_data_size": 0,
            "training_seconds": 0.0,
            "eval_seconds": 0.0,
            "cancelled": False,
            "error": None,
            "champion_path": None,
            "champion_avg": 0.0,
        },
        {"recursion_limit": 100},
    )

    assert final["generation"] == 4
    decisions = [s for s in states if s[0] == "promote_or_discard"]
    assert len(decisions) == 4
    assert decisions[0][2] == "promote"  # gen 1 has no champion → always promote
    assert decisions[1][2] == "discard"  # gen 2 regresses
    assert decisions[2][2] == "promote"
    assert decisions[3][2] == "promote"

    # New node is part of the traversal.
    steps = [s[0] for s in states]
    assert "identify_weaknesses" in steps
    # For gen 1, identify_weaknesses must happen before training data generation.
    i = steps.index("identify_weaknesses")
    j = steps.index("generate_training")
    assert i < j


@pytest.mark.asyncio
async def test_graph_respects_cancellation():
    cancelled_state = {"flag": False}

    async def cb(state: Any, step: str) -> None:
        # Cancel right after the first node fires.
        if step == "init_run" and not cancelled_state["flag"]:
            state["cancelled"] = True
            cancelled_state["flag"] = True

    graph = build_graph(
        training=MockTrainingBackend(0.0),
        eval_backend=MockEvalBackend(0.0),
        curator=MockDataCurator(),
        on_state_change=cb,
    )

    final = await graph.ainvoke(
        {
            "run_id": "cancel",
            "config": {"max_generations": 5},
            "generation": 0,
            "max_generations": 5,
            "cancelled": False,
            "error": None,
            "champion_avg": 0.0,
            "parent_scores": {},
            "child_scores": {},
        },
        {"recursion_limit": 100},
    )
    # Cancel flag is honoured by the conditional edge → graph exits early.
    assert final["cancelled"] is True
    assert final["generation"] == 1
