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
from services.data_curator import CurationResult, DataCuratorBackend

logger = logging.getLogger("modelforge.agents.graph")


# ── State ────────────────────────────────────────────────────────
class EvolutionState(TypedDict, total=False):
    run_id: str
    config: dict
    generation: int
    max_generations: int
    parent_scores: dict[str, float]
    child_scores: dict[str, float]
    weak_categories: list[str]
    weakness_report: str
    training_data_path: str | None
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
    curator: DataCuratorBackend,
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

    async def identify_weaknesses(state: EvolutionState) -> EvolutionState:
        """Analyze parent scores to decide which benchmarks to target next."""
        parent_scores = state.get("parent_scores", {})

        if not parent_scores:
            # First generation — no data yet, train broadly
            state["weak_categories"] = ["mmlu", "arc_challenge", "hellaswag", "gsm8k", "humaneval"]
            state["weakness_report"] = "Initial generation — broad training"
            await _emit(state, "identify_weaknesses")
            return state

        avg = sum(parent_scores.values()) / len(parent_scores)
        threshold = 0.55  # Absolute minimum acceptable score
        min_score = min(parent_scores.values())

        weak: list[str] = []
        analysis_lines: list[str] = []

        for bench, score in sorted(parent_scores.items(), key=lambda x: x[1]):
            is_weak = False
            reasons: list[str] = []

            if score < threshold:
                is_weak = True
                reasons.append(f"below absolute threshold ({score:.3f} < {threshold})")
            if score < avg * 0.90:
                is_weak = True
                reasons.append(f"below 90% of average ({score:.3f} < {avg*0.90:.3f})")
            if score == min_score:
                is_weak = True
                reasons.append("lowest scoring benchmark")

            if is_weak:
                weak.append(bench)
                analysis_lines.append(f"  {bench}: {score:.3f} — {', '.join(reasons)}")

        if not weak:
            weakest = min(parent_scores, key=parent_scores.get)
            weak = [weakest]
            analysis_lines.append(
                f"  {weakest}: {parent_scores[weakest]:.3f} — targeted as lowest"
            )

        report = f"Generation {state['generation']} weakness analysis:\n"
        report += f"  Average score: {avg:.3f}\n"
        report += f"  Weak categories ({len(weak)}):\n"
        report += "\n".join(analysis_lines)

        state["weak_categories"] = weak
        state["weakness_report"] = report

        logger.info("[weakness] gen=%d weak=%s", state["generation"], weak)
        await _emit(state, "identify_weaknesses")
        return state

    async def generate_training(state: EvolutionState) -> EvolutionState:
        weak = state.get("weak_categories") or ["mmlu", "arc_challenge", "hellaswag", "gsm8k", "humaneval"]
        report = state.get("weakness_report", "No analysis available")
        logger.info("[training-data] targeting %d categories: %s", len(weak), weak)

        max_samples = int((state.get("config") or {}).get("max_samples", 3000))
        try:
            result: CurationResult = await curator.curate(
                weak_categories=weak,
                weakness_report=report,
                generation=int(state.get("generation", 0) or 0),
                max_samples=max_samples,
                config=state.get("config", {}) or {},
            )
            state["training_data_path"] = result.data_path
            state["training_data_size"] = int(result.num_samples)
        except Exception as exc:
            logger.warning("[training-data] curator failed: %s", exc)
            state["training_data_path"] = None
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
    graph.add_node("identify_weaknesses", identify_weaknesses)
    graph.add_node("generate_training", generate_training)
    graph.add_node("train_adapter", train_adapter)
    graph.add_node("evaluate", evaluate)
    graph.add_node("compare_to_champion", compare_to_champion)
    graph.add_node("promote_or_discard", promote_or_discard)

    graph.set_entry_point("init_run")
    graph.add_edge("init_run", "identify_weaknesses")
    graph.add_edge("identify_weaknesses", "generate_training")
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
