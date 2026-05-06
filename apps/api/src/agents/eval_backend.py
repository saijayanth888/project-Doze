"""Evaluation backend protocol + Mock (Mac) and lm-eval-harness (DGX).

``MockEvalBackend`` produces a deterministic improvement curve aligned
with ``services.mock_data.mock_score_trends`` so the frontend gets the
same shape during local dev as in production.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Protocol

logger = logging.getLogger("modelforge.agents.eval")

_BENCHMARKS: tuple[str, ...] = ("mmlu", "arc_challenge", "hellaswag", "gsm8k", "humaneval")
_BASE_SCORES: dict[str, float] = {
    "mmlu": 0.612,
    "arc_challenge": 0.578,
    "hellaswag": 0.721,
    "gsm8k": 0.412,
    "humaneval": 0.298,
}
_DELTAS: dict[str, float] = {
    "mmlu": 0.017,
    "arc_challenge": 0.017,
    "hellaswag": 0.014,
    "gsm8k": 0.020,
    "humaneval": 0.017,
}
# Generations 1, 3, 4 always promote; 2 regresses. Matches mock_data.
_PROMOTED_GENS: frozenset[int] = frozenset({1, 3, 4})


@dataclass
class EvalResult:
    scores: dict[str, float] = field(default_factory=dict)
    duration_seconds: float = 0.0


class EvalBackend(Protocol):
    name: str

    async def evaluate(
        self,
        *,
        run_id: str,
        generation: int,
        adapter_path: str | None,
        config: dict | None = None,
    ) -> EvalResult: ...


# ── Mock (Mac dev) ───────────────────────────────────────────────
class MockEvalBackend:
    name = "mock"

    def __init__(self, sleep_s: float = 0.3) -> None:
        self._sleep_s = sleep_s

    async def evaluate(
        self,
        *,
        run_id: str,
        generation: int,
        adapter_path: str | None,
        config: dict | None = None,
    ) -> EvalResult:
        await asyncio.sleep(self._sleep_s)

        promoted = generation in _PROMOTED_GENS
        scores: dict[str, float] = {}
        for bm in _BENCHMARKS:
            base = _BASE_SCORES[bm]
            delta = _DELTAS[bm]
            value = base + delta * (generation - 1)
            if promoted:
                value += delta
            else:
                value -= 0.006
            scores[bm] = round(value, 4)

        logger.info(
            "[mock-eval] run=%s gen=%d avg=%.4f",
            run_id,
            generation,
            sum(scores.values()) / len(scores),
        )
        return EvalResult(scores=scores, duration_seconds=self._sleep_s)


# ── lm-eval-harness (DGX Spark) ──────────────────────────────────
class LMEvalHarnessBackend:
    name = "lm_eval"

    def __init__(self) -> None:
        try:
            import lm_eval  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "LMEvalHarnessBackend requires `lm-eval`. "
                "Install via the [gpu] extra on DGX Spark."
            ) from exc

    async def evaluate(
        self,
        *,
        run_id: str,
        generation: int,
        adapter_path: str | None,
        config: dict | None = None,
    ) -> EvalResult:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._evaluate_sync,
            run_id,
            generation,
            adapter_path,
            config,
        )

    def _evaluate_sync(
        self,
        run_id: str,
        generation: int,
        adapter_path: str | None,
        config: dict | None,
    ) -> EvalResult:
        import lm_eval

        from utils.hf_model_id import resolve_hf_base_model_id

        t0 = time.perf_counter()
        cfg_bm = (config or {}).get("base_model")
        base_model = resolve_hf_base_model_id(
            str(cfg_bm).strip() if cfg_bm else None,
            env_fallback=os.environ.get("MODELFORGE_BASE_MODEL"),
        )

        quick_eval = str(os.environ.get("MODELFORGE_QUICK_EVAL", "")).lower() in {"1", "true", "yes"}
        if quick_eval:
            tasks = ["mmlu"]
            num_fewshot = 0
            limit = 100
        else:
            tasks = list(_BENCHMARKS)
            num_fewshot = 5
            limit = None

        scores: dict[str, float] = {}
        logger.info(
            "[lm-eval] run=%s gen=%d base=%s adapter=%s quick=%s tasks=%s",
            run_id,
            generation,
            base_model,
            adapter_path,
            quick_eval,
            tasks,
        )

        for task in tasks:
            try:
                model_args = f"pretrained={base_model}"
                if adapter_path:
                    model_args = f"{model_args},peft={adapter_path}"

                results = lm_eval.simple_evaluate(
                    model="hf",
                    model_args=model_args,
                    tasks=[task],
                    num_fewshot=num_fewshot,
                    batch_size=8,
                    device="cuda",
                    limit=limit,
                )
                logger.info("[lm-eval] raw results (%s): %s", task, results)
                r = (results or {}).get("results", {}).get(task, {}) or {}
                score = r.get("acc_norm,none")
                if score is None:
                    score = r.get("acc,none", 0.0)
                scores[task] = float(score or 0.0)
            except Exception as exc:
                logger.exception("[lm-eval] task failed (%s): %s", task, exc)
                scores[task] = 0.0

        elapsed = time.perf_counter() - t0
        logger.info("[lm-eval] run=%s gen=%d scores=%s (%.1fs)", run_id, generation, scores, elapsed)
        return EvalResult(scores=scores, duration_seconds=float(elapsed))
