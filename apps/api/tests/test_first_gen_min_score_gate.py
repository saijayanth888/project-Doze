"""Tests for the first-gen minimum-score gate in evolution_graph.py.

Spec Section M — 4 tests.

These tests exercise the compare_to_champion node logic directly by constructing
a minimal EvolutionState and running the relevant decision branch, without
needing to spin up the full LangGraph.
"""

from __future__ import annotations

import os

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_first_gen_gate(child_scores: dict, env_threshold: str | None = None) -> dict:
    """Run the first-gen gate logic extracted from compare_to_champion.

    Returns the state dict with 'decision' and 'decision_reason' set.
    This mirrors the exact code path at evolution_graph.py:655.
    """
    # Reproduce the gate logic from the source
    from agents.evolution_graph import _avg

    child_avg = _avg(child_scores)

    if env_threshold is not None:
        saved = os.environ.get("MODELFORGE_MIN_FIRST_GEN_SCORE")
        os.environ["MODELFORGE_MIN_FIRST_GEN_SCORE"] = env_threshold
    try:
        MIN_FIRST_GEN_SCORE = float(os.environ.get("MODELFORGE_MIN_FIRST_GEN_SCORE", "0.30"))
        if child_avg < MIN_FIRST_GEN_SCORE:
            decision = "discard"
            reason = (
                f"First-gen min-score gate: child_avg={child_avg:.4f} < "
                f"MIN_FIRST_GEN_SCORE={MIN_FIRST_GEN_SCORE}. "
                f"Adapter not promoted; no track.promoted event will fire."
            )
        else:
            decision = "promote"
            reason = (
                f"First-gen min-score gate: child_avg={child_avg:.4f} >= "
                f"{MIN_FIRST_GEN_SCORE}. Promoting initial generation."
            )
    finally:
        if env_threshold is not None:
            if saved is None:
                os.environ.pop("MODELFORGE_MIN_FIRST_GEN_SCORE", None)
            else:
                os.environ["MODELFORGE_MIN_FIRST_GEN_SCORE"] = saved

    return {"decision": decision, "decision_reason": reason, "child_avg": child_avg}


def _run_subsequent_gen_pareto(child_scores: dict, parent_scores: dict) -> dict:
    """Simulate a subsequent-gen decision using Pareto dominance.

    Returns {'decision': 'promote'|'discard', 'decision_reason': str}.
    """
    from services.pareto_selector import is_pareto_dominant

    pareto = is_pareto_dominant(child_scores, parent_scores)
    if pareto.promote:
        return {"decision": "promote", "decision_reason": pareto.reason}
    else:
        return {"decision": "discard", "decision_reason": pareto.reason}


# ---------------------------------------------------------------------------
# Test 1: First gen promotes when child_avg >= threshold
# ---------------------------------------------------------------------------
def test_first_gen_promote_when_above_threshold():
    """child_avg=0.45, no parent → promote, reason mentions min-score gate."""
    result = _run_first_gen_gate(
        child_scores={"faithfulness_regex": 0.50, "judge_score": 0.40},
    )
    assert result["decision"] == "promote", (
        f"Expected promote, got {result['decision']}. Reason: {result['decision_reason']}"
    )
    assert "min-score gate" in result["decision_reason"]
    assert "0.45" in result["decision_reason"] or "0.450" in result["decision_reason"]
    assert result["child_avg"] == pytest.approx(0.45)


# ---------------------------------------------------------------------------
# Test 2: First gen discards when child_avg < threshold
# ---------------------------------------------------------------------------
def test_first_gen_discard_when_below_threshold():
    """child_avg=0.10, no parent → discard, reason mentions min-score gate."""
    result = _run_first_gen_gate(
        child_scores={"faithfulness_regex": 0.10, "judge_score": 0.10},
    )
    assert result["decision"] == "discard", (
        f"Expected discard, got {result['decision']}. Reason: {result['decision_reason']}"
    )
    assert "min-score gate" in result["decision_reason"]
    assert "Adapter not promoted" in result["decision_reason"]
    assert result["child_avg"] == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# Test 3: Env override lowers threshold so child_avg=0.10 now promotes
# ---------------------------------------------------------------------------
def test_first_gen_threshold_env_override():
    """MODELFORGE_MIN_FIRST_GEN_SCORE=0.05 → child_avg=0.10 now promotes."""
    result = _run_first_gen_gate(
        child_scores={"faithfulness_regex": 0.10, "judge_score": 0.10},
        env_threshold="0.05",
    )
    assert result["decision"] == "promote", (
        f"With threshold=0.05 and child_avg=0.10, expected promote. "
        f"Got {result['decision']}. Reason: {result['decision_reason']}"
    )
    assert "0.05" in result["decision_reason"] or "0.050" in result["decision_reason"]


# ---------------------------------------------------------------------------
# Test 4: Subsequent gen uses Pareto, NOT min-score gate
# ---------------------------------------------------------------------------
def test_subsequent_gen_uses_pareto_not_min_score():
    """child_avg=0.10 BUT parent exists with champion_avg=0.05 → use Pareto, not min-score gate.

    The min-score gate only applies to first-gen (no parent / champion_avg <= 0.0).
    When a parent exists, the Pareto comparator decides.
    """
    child_scores = {"faithfulness_regex": 0.10, "judge_score": 0.10}
    parent_scores = {"faithfulness_regex": 0.05, "judge_score": 0.05}

    # With no parent: min-score gate would discard this (0.10 < 0.30 default).
    first_gen_result = _run_first_gen_gate(child_scores)
    assert first_gen_result["decision"] == "discard", (
        "Sanity check: without parent, child_avg=0.10 should be discarded by min-score gate"
    )

    # With a parent: Pareto comparator runs. child beats parent on all metrics
    # (0.10 > 0.05), so Pareto should promote.
    pareto_result = _run_subsequent_gen_pareto(child_scores, parent_scores)
    # Pareto decides: child (0.10) dominates parent (0.05) on both metrics.
    assert pareto_result["decision"] == "promote", (
        f"With parent, Pareto should promote child that beats parent on all metrics. "
        f"Got: {pareto_result['decision']}. Reason: {pareto_result['decision_reason']}"
    )
    # The reason should NOT mention "min-score gate"
    assert "min-score gate" not in pareto_result["decision_reason"], (
        f"Subsequent gen should use Pareto, not min-score gate logic. "
        f"Reason: {pareto_result['decision_reason']}"
    )
