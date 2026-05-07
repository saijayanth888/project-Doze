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
from collections.abc import Callable
from typing import Protocol

logger = logging.getLogger("modelforge.agents.eval")

_BENCHMARKS: tuple[str, ...] = ("mmlu", "arc_challenge", "hellaswag", "gsm8k", "humaneval")

# Per-benchmark lm-eval configuration. The KEY is the public benchmark name
# stored in DB / shown in UI. The `task` field is the actual lm-eval task id
# we run — e.g. we evaluate "gsm8k" via the CoT variant `gsm8k_cot` because
# instruct models score ~0 on the loglikelihood `gsm8k` task; same reason we
# pick `humaneval_instruct` for instruct-tuned bases. `num_fewshot` follows
# the canonical evals (ARC=25, HellaSwag=10, MMLU=5, GSM8K-CoT=8, HumanEval=0).
# `score_keys` is tried in order; first hit wins. `gen_kwargs` and
# `requires_code_exec` are forwarded to simple_evaluate when present.
_TASK_CONFIG: dict[str, dict] = {
    "mmlu": {
        "task": "mmlu",
        "num_fewshot": 5,
        "score_keys": ("acc,none", "acc_norm,none"),
    },
    "arc_challenge": {
        "task": "arc_challenge",
        "num_fewshot": 25,
        "score_keys": ("acc_norm,none", "acc,none"),
    },
    "hellaswag": {
        "task": "hellaswag",
        "num_fewshot": 10,
        "score_keys": ("acc_norm,none", "acc,none"),
    },
    "gsm8k": {
        "task": "gsm8k_cot",
        "instruct_task": "gsm8k_cot",
        "num_fewshot": 8,
        "score_keys": (
            "exact_match,flexible-extract",
            "exact_match,strict-match",
            "exact_match,none",
        ),
        "gen_kwargs": {"max_gen_toks": 1024, "temperature": 0, "do_sample": False},
    },
    "humaneval": {
        "task": "humaneval",
        "instruct_task": "humaneval_instruct",
        "num_fewshot": 0,
        "score_keys": (
            "pass@1,create_test",
            "pass@1,none",
            "pass_at_1,none",
        ),
        "gen_kwargs": {"max_gen_toks": 512, "temperature": 0.1, "do_sample": False},
        "requires_code_exec": True,
    },
}

# Back-compat: kept so external callers / older tests that import this name
# don't break. New code should read `_TASK_CONFIG[name]["score_keys"]`.
_TASK_METRICS: dict[str, tuple[str, ...]] = {
    name: tuple(cfg["score_keys"]) for name, cfg in _TASK_CONFIG.items()
}

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
    harness_version: str = ""
    stderrs: dict[str, float] = field(default_factory=dict)


class EvalStopped(Exception):
    """Raised when ``should_stop()`` returns True between benchmarks.

    Lets the campaign / evolve runner abort an in-flight evaluation without
    waiting for the full multi-benchmark sweep to finish — Stop in the UI
    engages at the next benchmark boundary instead of after the full eval.
    """


class EvalBackend(Protocol):
    name: str

    async def evaluate(
        self,
        *,
        run_id: str,
        generation: int,
        adapter_path: str | None,
        config: dict | None = None,
        should_stop: Callable[[], bool] | None = None,
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
        should_stop: Callable[[], bool] | None = None,
    ) -> EvalResult:
        await asyncio.sleep(self._sleep_s)
        if should_stop and should_stop():
            raise EvalStopped("mock eval stopped by user")

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
def _extract_lm_eval_score(task: str, results: dict) -> float:
    """Find the canonical metric for ``task`` in the lm-eval results dict.

    lm-eval reports per-task metrics under composite keys like
    ``"acc,none"``, ``"exact_match,strict-match"``, ``"pass@1,create_test"``.
    We try the task's known keys first (in order of preference), then fall
    back to scanning for any ``score,filter``-style key that isn't a stderr.
    Returns ``0.0`` only when nothing usable is present.
    """
    candidates: list[str] = list(_TASK_METRICS.get(task, ()))
    candidates += ["acc,none", "acc_norm,none"]
    for key in candidates:
        v = results.get(key)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    # Generic last-ditch: first non-stderr metric value in the dict.
    for key, value in results.items():
        if not isinstance(key, str):
            continue
        if "_stderr" in key or "alias" == key:
            continue
        if "," not in key:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


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
        should_stop: Callable[[], bool] | None = None,
        bench_callback: Callable[[str], None] | None = None,
    ) -> EvalResult:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._evaluate_sync,
            run_id,
            generation,
            adapter_path,
            config,
            should_stop,
            bench_callback,
        )

    def _evaluate_sync(
        self,
        run_id: str,
        generation: int,
        adapter_path: str | None,
        config: dict | None,
        should_stop: Callable[[], bool] | None = None,
        bench_callback: Callable[[str], None] | None = None,
    ) -> EvalResult:
        import inspect as _inspect

        import lm_eval

        from utils.hf_model_id import resolve_hf_base_model_id

        harness_version = getattr(lm_eval, "__version__", "unknown")

        # HumanEval refuses to score without this on the harness side.
        os.environ.setdefault("HF_ALLOW_CODE_EVAL", "1")

        t0 = time.perf_counter()
        cfg_bm = (config or {}).get("base_model")
        base_model = resolve_hf_base_model_id(
            str(cfg_bm).strip() if cfg_bm else None,
            env_fallback=os.environ.get("MODELFORGE_BASE_MODEL"),
        )
        is_instruct = any(
            tag in str(base_model).lower() for tag in ("instruct", "chat", "-it")
        )

        quick_eval = str(os.environ.get("MODELFORGE_QUICK_EVAL", "")).lower() in {"1", "true", "yes"}
        if quick_eval:
            bench_names = ["mmlu"]
            limit_override: int | None = 100
        else:
            bench_names = list(_BENCHMARKS)
            limit_override = None

        # Allow callers to pin a smaller eval set / sample limit for ablations
        # without flipping the env var.
        cfg_limit = (config or {}).get("eval_limit")
        if isinstance(cfg_limit, int) and cfg_limit > 0:
            limit_override = cfg_limit

        # simple_evaluate kwargs vary across lm-eval versions; introspect once.
        sig_params = set(_inspect.signature(lm_eval.simple_evaluate).parameters.keys())

        scores: dict[str, float] = {}
        stderrs: dict[str, float] = {}
        logger.info(
            "[lm-eval] run=%s gen=%d base=%s adapter=%s instruct=%s quick=%s tasks=%s",
            run_id,
            generation,
            base_model,
            adapter_path,
            is_instruct,
            quick_eval,
            bench_names,
        )

        for bench in bench_names:
            # Cooperative stop: the campaign runner flips a flag when the user
            # clicks Stop in the UI. Check at each benchmark boundary so we
            # bail out without waiting for the full multi-benchmark sweep.
            if should_stop and should_stop():
                logger.info("[lm-eval] run=%s aborting at bench=%s — stop requested", run_id, bench)
                raise EvalStopped(f"stopped before {bench}")

            # Surface the currently-running benchmark to the campaign runner so
            # the dashboard can show "Now evaluating: arc_challenge" instead of
            # appearing frozen for 30 minutes per experiment.
            if bench_callback:
                try:
                    bench_callback(bench)
                except Exception:
                    pass

            cfg = _TASK_CONFIG.get(bench)
            if not cfg:
                logger.warning("[lm-eval] unknown benchmark: %s", bench)
                scores[bench] = 0.0
                continue

            # Pick the instruct variant of the task when available + applicable
            # (e.g. humaneval_instruct for chat-tuned bases). `gsm8k_cot` works
            # for both base + instruct so its instruct_task points at the same id.
            task_id = cfg.get("instruct_task") if is_instruct and cfg.get("instruct_task") else cfg["task"]

            try:
                model_args = f"pretrained={base_model},dtype=bfloat16,trust_remote_code=True"
                if adapter_path:
                    model_args += f",peft={adapter_path}"

                kwargs: dict = dict(
                    model="hf",
                    model_args=model_args,
                    tasks=[task_id],
                    num_fewshot=int(cfg["num_fewshot"]),
                    batch_size="auto",
                    device="cuda",
                    limit=limit_override,
                )

                # Instruct models need the chat template applied or generative
                # tasks score near-zero. fewshot_as_multiturn is only meaningful
                # when a chat template is in play.
                if is_instruct and "apply_chat_template" in sig_params:
                    kwargs["apply_chat_template"] = True
                    if "fewshot_as_multiturn" in sig_params and int(cfg["num_fewshot"]) > 0:
                        kwargs["fewshot_as_multiturn"] = True

                # Generation kwargs forwarded to generate_until tasks.
                gen_kwargs = cfg.get("gen_kwargs")
                if gen_kwargs and "gen_kwargs" in sig_params:
                    kwargs["gen_kwargs"] = ",".join(f"{k}={v}" for k, v in gen_kwargs.items())

                # Code-execution opt-in for HumanEval-family tasks.
                if cfg.get("requires_code_exec") and "confirm_run_unsafe_code" in sig_params:
                    kwargs["confirm_run_unsafe_code"] = True

                results = lm_eval.simple_evaluate(**kwargs)
                r = (results or {}).get("results", {}).get(task_id, {}) or {}
                score = _extract_lm_eval_score(bench, r)
                logger.info(
                    "[lm-eval] %s (task=%s) = %.4f (keys=%s)",
                    bench,
                    task_id,
                    score,
                    [k for k in r.keys() if not k.endswith("_stderr,none") and "," in k],
                )
                scores[bench] = float(score)
                # Pull the matching stderr if present. lm-eval reports stderr keys as
                # "acc_stderr,none", "exact_match_stderr,strict-match", "pass@1_stderr,none"
                # — i.e. the score key with `_stderr` inserted before the `,`.
                stderr = 0.0
                score_keys = _TASK_CONFIG.get(bench, {}).get("score_keys", ())
                for sk in score_keys:
                    if "," in sk:
                        prefix, _, suffix = sk.partition(",")
                        stderr_key = f"{prefix}_stderr,{suffix}"
                    else:
                        stderr_key = f"{sk}_stderr"
                    val = r.get(stderr_key)
                    if isinstance(val, (int, float)):
                        stderr = float(val)
                        break
                stderrs[bench] = stderr
            except Exception as exc:
                logger.exception("[lm-eval] task failed (%s/%s): %s", bench, task_id, exc)
                scores[bench] = 0.0

        elapsed = time.perf_counter() - t0
        logger.info("[lm-eval] run=%s gen=%d scores=%s (%.1fs)", run_id, generation, scores, elapsed)
        return EvalResult(
            scores=scores,
            duration_seconds=float(elapsed),
            harness_version=harness_version,
            stderrs=stderrs,
        )
