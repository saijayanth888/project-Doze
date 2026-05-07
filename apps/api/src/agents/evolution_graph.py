"""LangGraph evolution orchestrator.

State machine::

      ┌──────────────┐
      │ init_run     │
      └──────┬───────┘
             ▼
   ┌─────────────────────┐
   │ generate_training   │   (pull from HuggingFace via curator)
   └─────────┬───────────┘
             ▼
   ┌─────────────────────┐
   │ augment_training    │   (self-generated samples via Ollama)
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
   │ compare_to_champion │   (avg + per-bench regression + held-out)
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

import asyncio
import logging
import os
import random
import re
import time
from typing import Any, TypedDict

import httpx
from langgraph.graph import END, StateGraph

from agents.eval_backend import EvalBackend, EvalResult
from agents.training_backend import TrainingBackend, TrainingResult
from services import run_events
from services.data_curator import CurationResult, DataCuratorBackend

ALL_BENCHMARKS = ["mmlu", "arc_challenge", "hellaswag", "gsm8k", "humaneval"]
SELF_GEN_SEED_COUNT = int(os.environ.get("MODELFORGE_SELF_GEN_SEEDS", "50"))
SELF_GEN_TEACHER_TAG = os.environ.get("MODELFORGE_SELF_GEN_TEACHER", "llama3.2:3b")

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
    # Methodology bookkeeping (Phase-3 patch — research validity).
    curated_sample_count: int
    self_generated_count: int
    trained_benchmarks: list[str]
    held_out_benchmarks: list[str]
    trained_benchmark_delta: float | None
    held_out_benchmark_delta: float | None
    regression_report: dict[str, Any] | None
    eval_seconds: float
    harness_version: str
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

    def _phase_start(state: EvolutionState, *, phase: str, label: str, sub: str | None = None) -> None:
        """Publish a 'phase started' event to the in-process event buffer.

        Pure synchronous best-effort — never raises, never blocks. Lets the UI
        flip from "training" to "evaluating" the moment the eval node begins,
        instead of 3 hours later when it ends.
        """
        try:
            run_events.publish(
                state.get("run_id", ""),
                phase=phase,
                label=label,
                sub=sub,
                generation=state.get("generation"),
            )
        except Exception:
            pass

    # ── Nodes ────────────────────────────────────────────────────
    async def init_run(state: EvolutionState) -> EvolutionState:
        state["generation"] = state.get("generation", 0) + 1
        state["decision"] = ""
        state["decision_reason"] = ""
        state["error"] = None
        cfg = state.get("config", {}) or {}
        _phase_start(
            state,
            phase="init",
            label=f"Generation {state['generation']} starting",
            sub=f"base={cfg.get('base_model')} · LoRA r={cfg.get('lora_rank')} · max_samples={cfg.get('max_samples')}",
        )
        await _emit(state, "init_run")
        return state

    async def identify_weaknesses(state: EvolutionState) -> EvolutionState:
        """Analyze parent scores to decide which benchmarks to target next."""
        parent_scores = state.get("parent_scores", {})
        _phase_start(
            state,
            phase="identify",
            label="Identifying weaknesses",
            sub=(
                "no parent scores — broad training" if not parent_scores
                else f"comparing {len(parent_scores)} benchmark scores"
            ),
        )

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
            weakest = min(parent_scores, key=lambda k: parent_scores[k])
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

        max_samples = int((state.get("config") or {}).get("max_samples") or 3000)
        _phase_start(
            state,
            phase="curate",
            label="Curating training data",
            sub=f"targeting {len(weak)} categories · budget {max_samples} samples",
        )
        # Inject run_id into the config so the curator can publish per-dataset
        # progress events under the correct buffer key.
        cfg_for_curate = {**(state.get("config", {}) or {}), "run_id": state.get("run_id", "")}
        try:
            result: CurationResult = await curator.curate(
                weak_categories=weak,
                weakness_report=report,
                generation=int(state.get("generation", 0) or 0),
                max_samples=max_samples,
                config=cfg_for_curate,
            )
            state["training_data_path"] = result.data_path
            state["training_data_size"] = int(result.num_samples)
            # Methodology bookkeeping for the paper: how many came from
            # HuggingFace vs how many we'll add via self-distillation, plus
            # which benchmarks the curator actually targeted.
            state["curated_sample_count"] = int(result.num_samples)
            state["self_generated_count"] = 0
            state["trained_benchmarks"] = list(result.categories_targeted or weak)
            state["held_out_benchmarks"] = [b for b in ALL_BENCHMARKS if b not in (result.categories_targeted or weak)]
            run_events.publish(
                state.get("run_id", ""),
                phase="curate",
                label=f"Curation complete — {result.num_samples} samples",
                sub=f"sources: {', '.join(result.sources or [])[:200]}",
                generation=state.get("generation"),
            )
        except Exception as exc:
            logger.warning("[training-data] curator failed: %s", exc)
            state["training_data_path"] = None
            state["curated_sample_count"] = 0
            state["self_generated_count"] = 0
            state["trained_benchmarks"] = list(weak)
            state["held_out_benchmarks"] = [b for b in ALL_BENCHMARKS if b not in weak]
            run_events.publish(
                state.get("run_id", ""),
                phase="curate",
                level="error",
                label="Curation failed",
                sub=str(exc)[:300],
                generation=state.get("generation"),
            )
        await _emit(state, "generate_training")
        return state

    async def augment_training(state: EvolutionState) -> EvolutionState:
        """Self-distillation: ask the teacher model (via Ollama) to generate
        more training samples using random curated rows as few-shot seeds.

        Loads the curator's saved Arrow shard from disk, samples N seeds,
        prompts the teacher to write a new question+answer in the same style,
        validates each output, and writes the merged dataset back to the same
        path so train_adapter picks up everything.

        The teacher tag is `MODELFORGE_SELF_GEN_TEACHER` (default
        `llama3.2:3b`). Seed count is `MODELFORGE_SELF_GEN_SEEDS` (default 50).
        Set seeds to 0 to disable the augmentation phase entirely.
        """
        if state.get("cancelled"):
            return state
        path = state.get("training_data_path")
        if not path or SELF_GEN_SEED_COUNT <= 0:
            logger.info("[augment] skipped (no training_data_path or seeds=0)")
            await _emit(state, "augment_training")
            return state

        # Resolve the run's base model to its canonical HuggingFace id for
        # the experiment record. The teacher used for self-generation stays
        # `SELF_GEN_TEACHER_TAG` (an Ollama tag like `llama3.2:3b`) since the
        # call goes via Ollama; resolving the *run's* base model gives
        # downstream record consumers the unambiguous HF id without
        # re-deriving it.
        cfg = state.get("config", {}) or {}
        try:
            from utils.hf_model_id import resolve_hf_base_model_id
            base_hf_id = resolve_hf_base_model_id(cfg.get("base_model"))
        except Exception:
            base_hf_id = str(cfg.get("base_model") or "")
        state["base_model_hf_id"] = base_hf_id

        _phase_start(
            state,
            phase="curate",
            label="Augmenting with self-generated samples",
            sub=f"teacher={SELF_GEN_TEACHER_TAG} · base={base_hf_id} · seeds={SELF_GEN_SEED_COUNT}",
        )
        logger.info(
            "[augment] base_model=%s (resolved to HF id=%s) · teacher=%s · seeds=%d",
            cfg.get("base_model"), base_hf_id, SELF_GEN_TEACHER_TAG, SELF_GEN_SEED_COUNT,
        )

        # Lazy imports — keep evolution_graph importable in stripped-down envs.
        try:
            from datasets import Dataset, load_from_disk  # type: ignore
        except Exception as exc:
            logger.warning("[augment] datasets unavailable, skipping: %s", exc)
            await _emit(state, "augment_training")
            return state

        try:
            ds = load_from_disk(path)
            curated_rows = list(ds)
        except Exception as exc:
            logger.warning("[augment] could not load %s: %s", path, exc)
            await _emit(state, "augment_training")
            return state

        if len(curated_rows) < 10:
            logger.warning(
                "[augment] only %d curated rows — skipping self-generation",
                len(curated_rows),
            )
            await _emit(state, "augment_training")
            return state

        seeds = random.sample(curated_rows, min(SELF_GEN_SEED_COUNT, len(curated_rows)))
        ollama_host = os.environ.get("OLLAMA_HOST", "http://host.docker.internal:11434").rstrip("/")
        teacher = SELF_GEN_TEACHER_TAG

        async def gen_one(client: httpx.AsyncClient, seed: dict) -> dict | None:
            instruction = str(
                seed.get("instruction") or seed.get("question") or seed.get("text") or ""
            ).strip()
            answer = str(seed.get("response") or seed.get("output") or seed.get("answer") or "").strip()
            if not instruction:
                return None
            # Truncate examples so a verbose seed doesn't push the prompt past
            # the teacher's context window.
            instruction = instruction[:1200]
            answer = answer[:600]
            prompt = (
                "Here is an example question and answer:\n\n"
                f"Question: {instruction}\n"
                f"Answer: {answer}\n\n"
                "Now generate ONE NEW question in the same style and difficulty, "
                "with a correct answer.\n"
                "Format your response EXACTLY as:\n"
                "Question: <your question>\n"
                "Answer: <your answer>"
            )
            try:
                resp = await client.post(
                    f"{ollama_host}/api/generate",
                    json={
                        "model": teacher,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.8, "num_predict": 256},
                    },
                )
                if resp.status_code >= 400:
                    return None
                text = (resp.json().get("response") or "").strip()
            except Exception as exc:
                logger.debug("[augment] generation failed: %s", exc)
                return None

            # Lenient parse — the teacher often varies whitespace/casing.
            m = re.search(
                r"question\s*:\s*(.+?)\s*answer\s*:\s*(.+)$",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if not m:
                return None
            q = m.group(1).strip()
            a = m.group(2).strip()
            # Validation: non-trivial length, distinct from seed, plausible
            # max length so we don't ingest a runaway generation.
            if len(q) < 10 or len(a) < 5 or len(q) > 2000 or len(a) > 2000:
                return None
            if q.lower() == instruction.lower():
                return None
            return {
                "category": str(seed.get("category") or "self-gen"),
                "source": "self-generated",
                "dataset_name": f"ollama-self-gen:{teacher}",
                "instruction": q,
                "response": a,
            }

        generated: list[dict] = []
        # Bounded concurrency so we don't pin the teacher model with 50 parallel
        # calls. 4 in flight is a reasonable balance for a single-GPU host.
        sem = asyncio.Semaphore(4)
        async with httpx.AsyncClient(timeout=60.0) as client:
            async def worker(seed):
                async with sem:
                    return await gen_one(client, seed)
            results = await asyncio.gather(*(worker(s) for s in seeds), return_exceptions=True)
        for r in results:
            if isinstance(r, dict):
                generated.append(r)

        passed = len(generated)
        attempted = len(seeds)
        merged = curated_rows + generated
        try:
            Dataset.from_list(merged).save_to_disk(path)
            logger.info(
                "[augment] generated %d self-samples, %d passed validation, total dataset: %d",
                attempted, passed, len(merged),
            )
            run_events.publish(
                state.get("run_id", ""),
                phase="curate",
                label=f"Self-augmentation: +{passed} samples",
                sub=f"attempted {attempted} via {teacher} · curated+gen total {len(merged)}",
                metric={"attempted": attempted, "passed": passed, "total": len(merged)},
                generation=state.get("generation"),
            )
            state["self_generated_count"] = passed
            state["training_data_size"] = len(merged)
        except Exception as exc:
            logger.warning("[augment] save_to_disk failed, keeping curated only: %s", exc)
            run_events.publish(
                state.get("run_id", ""),
                phase="curate",
                level="warn",
                label="Self-augmentation save failed",
                sub=str(exc)[:200],
                generation=state.get("generation"),
            )

        await _emit(state, "augment_training")
        return state

    async def train_adapter(state: EvolutionState) -> EvolutionState:
        if state.get("cancelled"):
            return state
        cfg = state.get("config", {}) or {}
        _phase_start(
            state,
            phase="train",
            label=f"Training LoRA adapter (gen {state['generation']})",
            sub=f"base={cfg.get('base_model')} · batch={cfg.get('batch_size')} · LR={cfg.get('learning_rate')}",
        )
        # Surface the in-progress step to Postgres immediately. _emit at the
        # tail of the node only fires after training completes (~5 min), so
        # /api/evolve/status would otherwise stay on the *previous* step for
        # the entire run of this node.
        await _emit(state, "train_adapter")
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
        run_events.publish(
            state.get("run_id", ""),
            phase="train",
            label=f"Training complete in {state['training_seconds']:.1f}s",
            sub=f"adapter saved to {result.adapter_path}",
            generation=state.get("generation"),
        )
        await _emit(state, "train_adapter")
        return state

    async def evaluate(state: EvolutionState) -> EvolutionState:
        if state.get("cancelled"):
            return state
        _phase_start(
            state,
            phase="eval",
            label="Evaluating across benchmarks",
            sub="lm-eval mmlu · arc_challenge · hellaswag · gsm8k · humaneval",
        )
        # Surface the in-progress step to Postgres immediately. lm-eval-harness
        # takes ~2.5 hours per generation; without this early emit the dashboard
        # would show "train_adapter" the whole time. The tail _emit below still
        # fires once eval finishes, recording the same step idempotently.
        await _emit(state, "evaluate")
        t0 = time.perf_counter()
        result: EvalResult = await eval_backend.evaluate(
            run_id=state["run_id"],
            generation=state["generation"],
            adapter_path=state.get("adapter_path"),
            config=state.get("config") or {},
        )
        state["child_scores"] = result.scores
        state["eval_seconds"] = result.duration_seconds or (time.perf_counter() - t0)
        state["harness_version"] = result.harness_version or "unknown"
        # Per-benchmark recap so the user sees the exact scores in the events
        # feed without leaving the dashboard.
        for bench, score in (result.scores or {}).items():
            run_events.publish(
                state.get("run_id", ""),
                phase="eval",
                label=f"{bench} → {float(score):.3f}",
                metric={"benchmark": bench, "score": float(score)},
                generation=state.get("generation"),
            )
        run_events.publish(
            state.get("run_id", ""),
            phase="eval",
            label=f"Evaluation complete in {state['eval_seconds']:.1f}s",
            sub=f"{len(result.scores or {})} benchmarks scored",
            generation=state.get("generation"),
        )
        await _emit(state, "evaluate")
        return state

    async def compare_to_champion(state: EvolutionState) -> EvolutionState:
        _phase_start(
            state,
            phase="decide",
            label="Comparing to champion",
        )
        child_avg = _avg(state.get("child_scores", {}))
        champion_avg = state.get("champion_avg", 0.0)
        parent = state.get("parent_scores") or {}
        child = state.get("child_scores") or {}

        # ── Multi-objective Pareto-dominant selection ────────────────────
        # The previous "avg score went up" rule promoted models that gained
        # 5% on MMLU but lost 10% on GSM8K. Pareto dominance prevents that:
        # promote only if better on ≥1 benchmark AND not worse on any
        # benchmark by more than the threshold (default 0.01, override via
        # MODELFORGE_PARETO_THRESHOLD). First generation auto-promotes
        # because there's no parent to compare against.
        from services.pareto_selector import is_pareto_dominant
        pareto = is_pareto_dominant(child, parent)
        state["pareto_report"] = pareto.to_dict()

        if not parent or champion_avg <= 0.0:
            state["decision"] = "promote"
            state["decision_reason"] = "No prior champion — promoting initial generation"
        elif pareto.promote:
            state["decision"] = "promote"
            state["decision_reason"] = pareto.reason
        else:
            state["decision"] = "discard"
            state["decision_reason"] = pareto.reason

        # Log the avg context too — helps debugging when Pareto disagrees
        # with what the dashboard's avg-trend chart implies.
        logger.info(
            "[pareto] child_avg=%.4f champion_avg=%.4f decision=%s — %s",
            child_avg, champion_avg, state["decision"], pareto.reason,
        )

        # Per-benchmark regression guard: a model that gains 5% on MMLU but
        # loses 10% on GSM8K is a bad trade even when the average improves.
        # This kicks in only when we'd otherwise promote AND we have a real
        # parent to compare against. Configurable via
        # MODELFORGE_REGRESSION_THRESHOLD (default 0.03).
        if state["decision"] == "promote" and state.get("parent_scores"):
            from services.regression_detector import detect_regressions
            regression = detect_regressions(
                parent_scores=state.get("parent_scores"),
                child_scores=state.get("child_scores"),
            )
            state["regression_report"] = regression.to_dict()
            if regression.regression_detected:
                state["decision"] = "discard"
                state["decision_reason"] = (
                    f"Regression guard: avg {child_avg:.4f} > champion {champion_avg:.4f}, "
                    f"but {regression.summary()}"
                )
                run_events.publish(
                    state.get("run_id", ""),
                    phase="decide",
                    level="warn",
                    label="Regression guard triggered",
                    sub=regression.summary(),
                    generation=state.get("generation"),
                )

        # ── Cross-benchmark eval: trained vs held-out deltas ──────────────
        # The methodology question for the paper: did training on bench
        # subset T improve T at the cost of held-out benchmarks H? Compute
        # both averages so the generation row stores both, and discard if
        # held-out *regresses* by more than the threshold even when avg
        # improves.
        trained = state.get("trained_benchmarks") or list(ALL_BENCHMARKS)
        held_out = state.get("held_out_benchmarks") or [
            b for b in ALL_BENCHMARKS if b not in trained
        ]
        parent = state.get("parent_scores") or {}
        child = state.get("child_scores") or {}

        def _avg_delta(keys: list[str]) -> float | None:
            paired = [
                (float(child[k]) - float(parent[k]))
                for k in keys
                if isinstance(child.get(k), (int, float))
                and isinstance(parent.get(k), (int, float))
            ]
            return sum(paired) / len(paired) if paired else None

        trained_delta = _avg_delta(trained)
        held_out_delta = _avg_delta(held_out)
        state["trained_benchmark_delta"] = trained_delta
        state["held_out_benchmark_delta"] = held_out_delta
        logger.info(
            "[eval] trained benchmarks: %s, held-out benchmarks: %s",
            f"{(trained_delta or 0):+.4f}" if trained_delta is not None else "n/a",
            f"{(held_out_delta or 0):+.4f}" if held_out_delta is not None else "n/a",
        )

        # Held-out catastrophic-forgetting guard. Threshold reused so a single
        # env var (MODELFORGE_REGRESSION_THRESHOLD) governs both per-bench and
        # held-out tolerances. Only kicks in when we *have* held-out data.
        from services.regression_detector import _env_threshold
        threshold = _env_threshold(0.03)
        if (
            state["decision"] == "promote"
            and held_out
            and held_out_delta is not None
            and held_out_delta < -threshold
        ):
            state["decision"] = "discard"
            state["decision_reason"] = (
                f"Held-out regression guard: trained {trained_delta:+.4f} but "
                f"held-out ({', '.join(held_out)}) {held_out_delta:+.4f} "
                f"≤ -{threshold:.3f}. {state.get('decision_reason') or ''}"
            ).strip()
            run_events.publish(
                state.get("run_id", ""),
                phase="decide",
                level="warn",
                label="Held-out regression — generation discarded",
                sub=(
                    f"trained {trained_delta:+.4f} vs held-out {held_out_delta:+.4f}; "
                    f"held-out: {', '.join(held_out)}"
                ),
                metric={
                    "trained_delta": trained_delta,
                    "held_out_delta": held_out_delta,
                    "threshold": threshold,
                },
                generation=state.get("generation"),
            )

        await _emit(state, "compare_to_champion")
        return state

    async def promote_or_discard(state: EvolutionState) -> EvolutionState:
        decision = state.get("decision") or "?"
        _phase_start(
            state,
            phase="decide",
            label=("Promoting new champion" if decision == "promote" else "Discarding generation"),
            sub=str(state.get("decision_reason") or ""),
        )
        if state["decision"] == "promote":
            state["champion_avg"] = _avg(state.get("child_scores", {}))
            state["champion_path"] = state.get("adapter_path")
        # Advance parent_scores AFTER persistence: the runner's
        # on_state_change reads parent_scores at this _emit to build the
        # generation row. Advancing first would clobber the per-gen
        # parent→child delta in the saved record (parent==child for every
        # promoted gen). Next iteration's compare_to_champion still sees
        # the new champion as parent because we advance below.
        await _emit(state, "promote_or_discard")
        if state["decision"] == "promote":
            state["parent_scores"] = dict(state.get("child_scores", {}))
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
    graph.add_node("augment_training", augment_training)
    graph.add_node("train_adapter", train_adapter)
    graph.add_node("evaluate", evaluate)
    graph.add_node("compare_to_champion", compare_to_champion)
    graph.add_node("promote_or_discard", promote_or_discard)

    graph.set_entry_point("init_run")
    graph.add_edge("init_run", "identify_weaknesses")
    graph.add_edge("identify_weaknesses", "generate_training")
    graph.add_edge("generate_training", "augment_training")
    graph.add_edge("augment_training", "train_adapter")
    graph.add_edge("train_adapter", "evaluate")
    graph.add_edge("evaluate", "compare_to_champion")
    graph.add_edge("compare_to_champion", "promote_or_discard")
    graph.add_conditional_edges(
        "promote_or_discard",
        should_continue,
        {"loop": "init_run", "end": END},
    )

    return graph.compile()
