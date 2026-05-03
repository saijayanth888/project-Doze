"""LangGraph evolution orchestrator.

State machine::

      ┌──────────────┐
      │ init_run     │
      └──────┬───────┘
             ▼
   ┌─────────────────────┐
   │ generate_training   │   (pull champion, build dataset)
   └─────────┬───────────┘
             ▼
   ┌─────────────────────┐
   │ train_adapter       │   (LoRA / mock)
   └─────────┬───────────┘
             ▼
   ┌─────────────────────┐
   │ evaluate            │   (lm-eval / mock)
   └─────────┬───────────┘
             ▼
   ┌─────────────────────┐
   │ compare_to_champion │
   └─────────┬───────────┘
             ▼
   ┌─────────────────────┐
   │ promote_or_discard  │
   └─────────┬───────────┘
             ▼
   ┌─────────────────────┐
   │ next_or_finish      │   (loop or END)
   └─────────────────────┘
"""

from __future__ import annotations

import logging
import time
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from agents.eval_backend import EvalBackend, EvalResult
from agents.training_backend import TrainingBackend, TrainingResult

logger = logging.getLogger("modelforge.agents.graph")


# ── State ────────────────────────────────────────────────────────
class EvolutionState(TypedDict, total=False):
    run_id: str
    config: dict
    generation: int
    max_generations: int
    parent_scores: dict[str, float]
    child_scores: dict[str, float]
    decision: str  # "promote" | "discard" | ""
    decision_reason: str
    method: str
    adapter_path: str | None
    training_data_size: int
    training_seconds: float
    eval_seconds: float
    cancelled: bool
    error: str | None
    champion_path: str | None
    champion_avg: float


# ── Helpers ──────────────────────────────────────────────────────
def _avg(scores: dict[str, float]) -> float:
    return sum(scores.values()) / len(scores) if scores else 0.0


# ── Graph construction ───────────────────────────────────────────
def build_graph(
    *,
    training: TrainingBackend,
    eval_backend: EvalBackend,
    on_state_change: Any = None,
) -> Any:
    """Build and compile the LangGraph state machine.

    ``on_state_change`` is awaited (if provided) at the end of every
    node. It receives ``(state, current_step)`` so the runner can
    persist progress to Postgres for the WebSocket subscribers.
    """

    async def _emit(state: EvolutionState, step: str) -> None:
        if on_state_change is not None:
            try:
                await on_state_change(state, step)
            except Exception as exc:
                logger.warning("on_state_change(%s) failed: %s", step, exc)

    # ── Nodes ────────────────────────────────────────────────────
    async def init_run(state: EvolutionState) -> EvolutionState:
        state["generation"] = state.get("generation", 0) + 1
        state["decision"] = ""
        state["decision_reason"] = ""
        state["error"] = None
        await _emit(state, "init_run")
        return state

    async def generate_training(state: EvolutionState) -> EvolutionState:
        # Real impl: pull champion responses, deduplicate, score, build a
        # SFT dataset. The mock backend returns a synthetic count below.
        await _emit(state, "generate_training")
        return state

    async def train_adapter(state: EvolutionState) -> EvolutionState:
        if state.get("cancelled"):
            return state
        t0 = time.perf_counter()
        result: TrainingResult = await training.train(
            run_id=state["run_id"],
            generation=state["generation"],
            config=state.get("config", {}),
        )
        state["adapter_path"] = result.adapter_path
        state["method"] = result.method
        state["training_data_size"] = result.training_data_size
        state["training_seconds"] = result.duration_seconds or (time.perf_counter() - t0)
        await _emit(state, "train_adapter")
        return state

    async def evaluate(state: EvolutionState) -> EvolutionState:
        if state.get("cancelled"):
            return state
        t0 = time.perf_counter()
        result: EvalResult = await eval_backend.evaluate(
            run_id=state["run_id"],
            generation=state["generation"],
            adapter_path=state.get("adapter_path"),
        )
        state["child_scores"] = result.scores
        state["eval_seconds"] = result.duration_seconds or (time.perf_counter() - t0)
        await _emit(state, "evaluate")
        return state

    async def compare_to_champion(state: EvolutionState) -> EvolutionState:
        child_avg = _avg(state.get("child_scores", {}))
        champion_avg = state.get("champion_avg", 0.0)
        # The first generation has no champion to beat — promote any
        # successful run. Subsequent generations must outscore the
        # current champion by at least 0.001 to avoid noise-driven
        # promotions.
        if champion_avg <= 0.0:
            state["decision"] = "promote"
            state["decision_reason"] = "No prior champion — promoting initial generation"
        elif child_avg >= champion_avg + 0.001:
            state["decision"] = "promote"
            state["decision_reason"] = f"avg {child_avg:.4f} ≥ champion {champion_avg:.4f} + 0.001"
        else:
            state["decision"] = "discard"
            state["decision_reason"] = (
                f"avg {child_avg:.4f} did not beat champion {champion_avg:.4f}"
            )
        await _emit(state, "compare_to_champion")
        return state

    async def promote_or_discard(state: EvolutionState) -> EvolutionState:
        if state["decision"] == "promote":
            state["champion_avg"] = _avg(state.get("child_scores", {}))
            state["champion_path"] = state.get("adapter_path")
            state["parent_scores"] = dict(state.get("child_scores", {}))
        await _emit(state, "promote_or_discard")
        return state

    # ── Conditional edges ────────────────────────────────────────
    def should_continue(state: EvolutionState) -> str:
        if state.get("cancelled") or state.get("error"):
            return "end"
        if state["generation"] >= state.get("max_generations", 1):
            return "end"
        return "loop"

    graph = StateGraph(EvolutionState)
    graph.add_node("init_run", init_run)
    graph.add_node("generate_training", generate_training)
    graph.add_node("train_adapter", train_adapter)
    graph.add_node("evaluate", evaluate)
    graph.add_node("compare_to_champion", compare_to_champion)
    graph.add_node("promote_or_discard", promote_or_discard)

    graph.set_entry_point("init_run")
    graph.add_edge("init_run", "generate_training")
    graph.add_edge("generate_training", "train_adapter")
    graph.add_edge("train_adapter", "evaluate")
    graph.add_edge("evaluate", "compare_to_champion")
    graph.add_edge("compare_to_champion", "promote_or_discard")
    graph.add_conditional_edges(
        "promote_or_discard",
        should_continue,
        {"loop": "init_run", "end": END},
    )

    return graph.compile()
