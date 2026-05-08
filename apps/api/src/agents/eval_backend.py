"""Evaluation backend protocol + Mock (Mac) and lm-eval-harness (DGX).

``MockEvalBackend`` produces a deterministic improvement curve aligned
with ``services.mock_data.mock_score_trends`` so the frontend gets the
same shape during local dev as in production.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Protocol

logger = logging.getLogger("modelforge.agents.eval")

# ── In-flight eval abort signal ──────────────────────────────────
# lm-eval runs as a sync call inside a thread-pool executor; Python can't kill
# threads. To make force_stop actually interrupt the eval (not just mark the
# runner idle while the thread keeps churning), we set this event and the
# forward pre-hook registered on the loaded model raises EvalStopped on the
# next batch — typically <1s response time.
_eval_abort_event = threading.Event()


def request_eval_abort() -> None:
    """Signal the active eval thread to bail at the next model forward call.

    Called by campaign_runner.force_stop() so the GPU is released promptly
    instead of waiting for lm-eval to finish a 30-min MMLU sweep on its own.
    Safe to call when no eval is running — the next eval will clear the flag
    in its setup.
    """
    _eval_abort_event.set()


def clear_eval_abort() -> None:
    _eval_abort_event.clear()


# ── Eval subprocess runner ──────────────────────────────────────
_EVAL_WORKER_SCRIPT = "/app/src/scripts/eval_worker.py"


async def run_eval_subprocess(
    *,
    model: str,
    adapter_path: str | None = None,
    benchmarks: list[str] | None = None,
    limit: int | None = None,
    batch_size: str | None = None,
    on_benchmark_started: Callable[[str], None] | None = None,
    on_benchmark_complete: Callable[[str, float, float], None] | None = None,
    run_id: str | None = None,
    proc_holder: list | None = None,
) -> dict:
    """Spawn eval_worker.py and return its parsed result dict.

    Module-level helper used by LMEvalHarnessBackend.evaluate() (covers EPT
    and sequential evolution) and by CampaignRunner._run_eval_subprocess
    (campaign baseline). Subprocess isolation guarantees CUDA memory is
    fully reclaimed on worker exit — see project_dgx_freeze_fingerprint
    memory for why in-process gc + cuda.empty_cache() leak 1-5 GB per call.

    Callbacks fire as the worker emits JSONL events on stdout. proc_holder,
    if provided, is appended with the spawned process so the caller can
    SIGTERM it from elsewhere (force_stop path).
    """
    bench_list = list(benchmarks) if benchmarks else list(_BENCHMARKS)
    benchmarks_arg = ",".join(bench_list)
    rid = run_id or f"eval-{int(time.time() * 1000)}"
    output_path = f"/tmp/eval-{rid}.json"

    cmd = [
        "python",
        _EVAL_WORKER_SCRIPT,
        "--model", model,
        "--output", output_path,
        "--benchmarks", benchmarks_arg,
    ]
    if adapter_path:
        cmd.extend(["--adapter", adapter_path])
    if isinstance(limit, int) and limit > 0:
        cmd.extend(["--limit", str(limit)])
    if batch_size:
        cmd.extend(["--batch-size", str(batch_size)])

    logger.info("[eval-subprocess] spawn: %s", " ".join(cmd))

    # 10 MiB readline buffer: lm-eval's tqdm progress concatenates updates with
    # \r (no newline until the bar finishes). The default 64 KiB limit blows
    # up on benchmarks like MMLU with thousands of progress updates per task —
    # readline raises LimitOverrunError and the eval is reported failed even
    # though the worker is still progressing.
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=10 * 1024 * 1024,
    )
    if proc_holder is not None:
        proc_holder.append(proc)

    async def _consume_stdout() -> None:
        assert proc.stdout is not None
        while True:
            line_bytes = await proc.stdout.readline()
            if not line_bytes:
                return
            line = line_bytes.decode(errors="replace").rstrip()
            if not line:
                continue
            if not line.startswith("EVENT: "):
                logger.info("[eval-subprocess stdout] %s", line)
                continue
            try:
                evt = json.loads(line[7:])
            except Exception:
                logger.debug("[eval-subprocess] non-JSON event: %s", line)
                continue
            et = evt.get("event")
            if et == "benchmark_started" and on_benchmark_started is not None:
                try:
                    on_benchmark_started(evt.get("benchmark"))
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[eval-subprocess] on_benchmark_started: %s", exc)
            elif et == "benchmark_complete" and on_benchmark_complete is not None:
                try:
                    on_benchmark_complete(
                        evt.get("benchmark"),
                        float(evt.get("score") or 0.0),
                        float(evt.get("stderr") or 0.0),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[eval-subprocess] on_benchmark_complete: %s", exc)
            elif et in ("worker_started", "model_loaded", "worker_complete", "worker_error"):
                logger.info("[eval-subprocess] %s: %s", et, {k: v for k, v in evt.items() if k != "event"})

    async def _consume_stderr() -> None:
        assert proc.stderr is not None
        while True:
            line_bytes = await proc.stderr.readline()
            if not line_bytes:
                return
            line = line_bytes.decode(errors="replace").rstrip()
            if line:
                logger.info("[eval-subprocess stderr] %s", line)

    try:
        await asyncio.gather(
            _consume_stdout(),
            _consume_stderr(),
            proc.wait(),
        )
    except asyncio.CancelledError:
        if proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            except Exception as exc:  # noqa: BLE001
                logger.debug("[eval-subprocess] terminate on cancel: %s", exc)
        raise

    rc = proc.returncode
    if rc not in (0, 3):
        try:
            os.unlink(output_path)
        except OSError:
            pass
        raise RuntimeError(f"eval-worker exited with code {rc}")

    try:
        with open(output_path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"eval-worker output unreadable: {exc}") from exc
    finally:
        try:
            os.unlink(output_path)
        except OSError:
            pass

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
        bench_callback: Callable[[str], None] | None = None,
        bench_complete_callback: Callable[[str, float, float], None] | None = None,
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
        bench_callback: Callable[[str], None] | None = None,
        bench_complete_callback: Callable[[str, float, float], None] | None = None,
    ) -> EvalResult:
        await asyncio.sleep(self._sleep_s)
        if should_stop and should_stop():
            raise EvalStopped("mock eval stopped by user")

        promoted = generation in _PROMOTED_GENS
        scores: dict[str, float] = {}
        for bm in _BENCHMARKS:
            if bench_callback:
                try:
                    bench_callback(bm)
                except Exception:
                    pass
            base = _BASE_SCORES[bm]
            delta = _DELTAS[bm]
            value = base + delta * (generation - 1)
            if promoted:
                value += delta
            else:
                value -= 0.006
            scores[bm] = round(value, 4)
            if bench_complete_callback:
                try:
                    bench_complete_callback(bm, scores[bm], 0.01)
                except Exception:
                    pass

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
        bench_complete_callback: Callable[[str, float, float], None] | None = None,
    ) -> EvalResult:
        """Evaluate a model in a fresh subprocess.

        Subprocess isolation is required on the DGX Spark unified-memory
        architecture: in-process gc + cuda.empty_cache() leak 1-5 GB per
        model, which after 4-5 evals freezes the host (NVRM
        `_memdescAllocInternal` OOM, see project_dgx_freeze_fingerprint
        memory). Process exit reclaims everything atomically.

        Callers (EPT, sequential evolution, campaign_runner) get the same
        protocol: scores dict + stderrs + duration. `should_stop` is checked
        once at the start; mid-eval cancellation requires SIGTERM via the
        caller (see CampaignRunner.force_stop). bench_callback / bench_
        complete_callback are forwarded as the worker emits JSONL events.
        """
        if should_stop and should_stop():
            raise EvalStopped("stopped before evaluate()")

        from utils.hf_model_id import resolve_hf_base_model_id

        cfg = config or {}
        cfg_bm = cfg.get("base_model")
        base_model = resolve_hf_base_model_id(
            str(cfg_bm).strip() if cfg_bm else None,
            env_fallback=os.environ.get("MODELFORGE_BASE_MODEL"),
        )

        # Pick benchmark set from config (EPT uses `eval_benchmarks`),
        # falling back to the canonical 5-task sweep.
        bench_list = (
            cfg.get("eval_benchmarks")
            or cfg.get("benchmarks")
            or list(_BENCHMARKS)
        )
        if not isinstance(bench_list, list):
            bench_list = list(_BENCHMARKS)

        eval_limit = cfg.get("eval_limit") or cfg.get("limit")

        result_dict = await run_eval_subprocess(
            model=base_model,
            adapter_path=adapter_path,
            benchmarks=bench_list,
            limit=int(eval_limit) if isinstance(eval_limit, int) and eval_limit > 0 else None,
            on_benchmark_started=bench_callback,
            on_benchmark_complete=bench_complete_callback,
            run_id=run_id,
        )

        return EvalResult(
            scores=dict(result_dict.get("scores") or {}),
            stderrs=dict(result_dict.get("stderrs") or {}),
            duration_seconds=float(result_dict.get("duration_seconds") or 0.0),
            harness_version=str(result_dict.get("harness_version") or ""),
        )

    def _evaluate_sync(
        self,
        run_id: str,
        generation: int,
        adapter_path: str | None,
        config: dict | None,
        should_stop: Callable[[], bool] | None = None,
        bench_callback: Callable[[str], None] | None = None,
        bench_complete_callback: Callable[[str, float, float], None] | None = None,
    ) -> EvalResult:
        try:
            return self._evaluate_sync_inner(
                run_id, generation, adapter_path, config,
                should_stop, bench_callback, bench_complete_callback,
            )
        finally:
            # Release allocator state between evals so a long-running API
            # process doesn't accumulate fragmented allocations across runs.
            # On DGX Spark unified memory the GPU and host share one pool, so
            # leftover CUDA buffers count against the same RAM the next eval's
            # weight load needs — without this drain + settle the host can
            # silently freeze when peak unified memory fills (no OOM in dmesg).
            import gc
            gc.collect()
            try:
                import torch as _torch
                if _torch.cuda.is_available():
                    _torch.cuda.empty_cache()
                    _torch.cuda.synchronize()
                    _torch.cuda.reset_peak_memory_stats()
                    if hasattr(_torch.cuda, "ipc_collect"):
                        _torch.cuda.ipc_collect()
            except Exception as exc:
                logger.debug("[lm-eval] cuda cleanup skipped: %s", exc)
            logger.info("[lm-eval] post-eval cleanup done, sleeping 30s for memory settle")
            time.sleep(30)

    def _evaluate_sync_inner(
        self,
        run_id: str,
        generation: int,
        adapter_path: str | None,
        config: dict | None,
        should_stop: Callable[[], bool] | None = None,
        bench_callback: Callable[[str], None] | None = None,
        bench_complete_callback: Callable[[str, float, float], None] | None = None,
    ) -> EvalResult:
        import inspect as _inspect

        import lm_eval

        from utils.hf_model_id import resolve_hf_base_model_id
        from utils.memory_guard import check_memory

        check_memory(min_gb=10.0, label=f"pre-eval run={run_id} gen={generation}")

        # Reset the abort flag from any prior force-stop so this fresh eval
        # isn't aborted before it starts.
        clear_eval_abort()

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

        # Pre-load the HF model ONCE and reuse it across all benchmarks.
        # Previously we passed model="hf"+model_args into each per-benchmark
        # simple_evaluate call, which caused lm-eval to re-instantiate the
        # full model (~14GB for a 7B at bf16) on every iteration. With 5
        # benchmarks × ~14GB and lazy GC, peak unified-memory usage on the
        # DGX Spark blew past the 96GB cap and crashed the host. Loading
        # once and passing the LM instance keeps us at one model copy for
        # the whole sweep while preserving per-task num_fewshot / gen_kwargs
        # (the bits that simple_evaluate would silently lose if we batched
        # all tasks into one call — lm-eval's task YAML defaults differ
        # from our canonical leaderboard config for arc/hellaswag/mmlu).
        model_args = f"pretrained={base_model},dtype=bfloat16,trust_remote_code=True"
        if adapter_path:
            model_args += f",peft={adapter_path}"
        lm_obj = lm_eval.api.registry.get_model("hf").create_from_arg_string(
            model_args,
            {"batch_size": "auto", "device": "cuda"},
        )

        # Forward pre-hook: lm-eval calls model(...) once per batch (~100s of
        # ms during eval). The hook raises EvalStopped when force_stop set the
        # abort flag, unwinding lm_eval.simple_evaluate immediately instead of
        # waiting for the next benchmark boundary.
        abort_hook_handle = None
        underlying_model = getattr(lm_obj, "model", None)
        if underlying_model is not None and hasattr(underlying_model, "register_forward_pre_hook"):
            def _abort_pre_hook(_module, _inputs):  # noqa: ANN001 — torch hook signature
                if _eval_abort_event.is_set():
                    raise EvalStopped("eval aborted by force_stop")
            try:
                abort_hook_handle = underlying_model.register_forward_pre_hook(_abort_pre_hook)
            except Exception as exc:  # noqa: BLE001
                logger.debug("[lm-eval] could not register abort pre-hook: %s", exc)

        try:
            for bench in bench_names:
                # Cooperative stop: the campaign runner flips a flag when the
                # user clicks Stop in the UI. Check at each benchmark boundary
                # so we bail out without waiting for the full sweep.
                if should_stop and should_stop():
                    logger.info("[lm-eval] run=%s aborting at bench=%s — stop requested", run_id, bench)
                    raise EvalStopped(f"stopped before {bench}")

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

                # Pick the instruct variant when applicable (humaneval_instruct
                # for chat-tuned bases; gsm8k_cot is shared).
                task_id = cfg.get("instruct_task") if is_instruct and cfg.get("instruct_task") else cfg["task"]

                try:
                    kwargs: dict = dict(
                        model=lm_obj,  # ← reuse the pre-loaded model
                        tasks=[task_id],
                        num_fewshot=int(cfg["num_fewshot"]),
                        batch_size="auto",
                        device="cuda",
                        limit=limit_override,
                    )

                    if is_instruct and "apply_chat_template" in sig_params:
                        kwargs["apply_chat_template"] = True
                        if "fewshot_as_multiturn" in sig_params and int(cfg["num_fewshot"]) > 0:
                            kwargs["fewshot_as_multiturn"] = True

                    gen_kwargs = cfg.get("gen_kwargs")
                    if gen_kwargs and "gen_kwargs" in sig_params:
                        kwargs["gen_kwargs"] = ",".join(f"{k}={v}" for k, v in gen_kwargs.items())

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
                    if bench_complete_callback:
                        try:
                            bench_complete_callback(bench, float(score), float(stderr))
                        except Exception:
                            pass

                    # Free the per-bench results dict + flush CUDA caches
                    # between benchmarks so transient generation buffers don't
                    # accumulate (the model itself stays loaded — that's the
                    # whole point of the outer pre-load).
                    del results
                    import gc as _gc
                    _gc.collect()
                    try:
                        import torch as _torch
                        if _torch.cuda.is_available():
                            _torch.cuda.empty_cache()
                            _torch.cuda.synchronize()
                    except Exception:
                        pass

                    try:
                        check_memory(min_gb=8.0, label=f"post-{bench} run={run_id}")
                    except RuntimeError as exc:
                        logger.error(
                            "[lm-eval] memory critically low after %s, aborting remaining benchmarks: %s",
                            bench, exc,
                        )
                        break
                except EvalStopped:
                    # Force-stop / cooperative-stop must escape the per-task
                    # handler so we don't loop into the next benchmark and
                    # immediately re-trigger the abort hook.
                    raise
                except Exception as exc:
                    logger.exception("[lm-eval] task failed (%s/%s): %s", bench, task_id, exc)
                    scores[bench] = 0.0
                    if bench_complete_callback:
                        try:
                            bench_complete_callback(bench, 0.0, 0.0)
                        except Exception:
                            pass
        finally:
            # Tear down the abort pre-hook so it doesn't leak into the next
            # eval (which will register its own on its freshly-loaded model).
            if abort_hook_handle is not None:
                try:
                    abort_hook_handle.remove()
                except Exception:
                    pass
            # Drop the model reference + flush before returning so the next
            # eval starts from a clean allocator state.
            try:
                del lm_obj
            except Exception:
                pass
            import gc as _gc
            _gc.collect()
            try:
                import torch as _torch
                if _torch.cuda.is_available():
                    _torch.cuda.empty_cache()
                    _torch.cuda.synchronize()
            except Exception:
                pass

        elapsed = time.perf_counter() - t0
        logger.info("[lm-eval] run=%s gen=%d scores=%s (%.1fs)", run_id, generation, scores, elapsed)
        return EvalResult(
            scores=scores,
            duration_seconds=float(elapsed),
            harness_version=harness_version,
            stderrs=stderrs,
        )
