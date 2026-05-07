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
async def test_promoted_generation_persists_real_parent_scores():
    """Regression: ``promote_or_discard`` advanced ``parent_scores`` to a copy
    of ``child_scores`` *before* the persistence callback fired, so every
    promoted generation row in the DB had ``parent_scores == child_scores``
    and a delta of zero — even when the decision_reason held real deltas
    computed earlier in ``compare_to_champion``.

    The fix: defer the advance until after ``_emit("promote_or_discard")``
    so the callback sees the original parent.
    """
    saved: list[dict[str, Any]] = []

    async def cb(state: Any, step: str) -> None:
        if step == "promote_or_discard":
            saved.append({
                "gen": state.get("generation"),
                "decision": state.get("decision"),
                "parent_scores": dict(state.get("parent_scores") or {}),
                "child_scores": dict(state.get("child_scores") or {}),
            })

    graph = build_graph(
        training=MockTrainingBackend(0.0),
        eval_backend=MockEvalBackend(0.0),
        curator=MockDataCurator(),
        on_state_change=cb,
    )

    await graph.ainvoke(
        {
            "run_id": "test-parent-snapshot",
            "config": {"max_generations": 4},
            "generation": 0,
            "max_generations": 4,
            "parent_scores": {},
            "child_scores": {},
            "decision": "",
            "decision_reason": "",
            "champion_avg": 0.0,
        },
        {"recursion_limit": 100},
    )

    # MockEvalBackend curve: gen 1 promote (no parent), gen 2 discard,
    # gen 3 promote, gen 4 promote — gens 3 and 4 have a real prior champion.
    promoted_with_parent = [
        s for s in saved
        if s["decision"] == "promote" and s["parent_scores"]
    ]
    assert promoted_with_parent, (
        "expected at least one promoted gen with non-empty parent_scores"
    )
    for s in promoted_with_parent:
        assert s["parent_scores"] != s["child_scores"], (
            f"gen {s['gen']}: parent_scores was clobbered to child_scores "
            f"before persistence — {s['parent_scores']}"
        )


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
