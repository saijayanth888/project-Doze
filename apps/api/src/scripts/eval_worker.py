#!/usr/bin/env python3
"""Eval worker — runs ONE model on N benchmarks in an isolated process.

Spawned by campaign_runner for eval_only experiments. Subprocess isolation is
the only way to fully reclaim CUDA memory on the DGX Spark unified-memory
architecture: gc.collect() and torch.cuda.empty_cache() leave 1-5 GB of
allocator state per model, which accumulates across 5+ baseline runs into a
silent host freeze (NVRM `_memdescAllocInternal` OOM — see
project_dgx_freeze_fingerprint memory). Process exit reclaims everything.

Output channels:
- stdout: JSONL progress events. Each event line is prefixed `EVENT: ` so
  the parent can distinguish events from lm-eval's own prints. Parent parses
  these to push live updates into the dashboard via bench_callback.
- stderr: lm-eval's tqdm progress bars + tracebacks (forwarded to docker logs).
- final results JSON at `--output`: full dict with scores, stderrs, duration.

Exit codes:
- 0   success, output JSON written, all benchmarks scored
- 1   write-output error
- 2   setup / model load error
- 3   at least one benchmark failed (other scores still in output)
- 130 SIGINT/SIGTERM (force_stop from parent)
"""
from __future__ import annotations

import argparse
import inspect
import json
import logging
import os
import signal
import sys
import time
from typing import Any

logger = logging.getLogger("eval-worker")


def _emit(event: str, **fields: Any) -> None:
    """Emit a single JSONL progress event on stdout, prefixed `EVENT: `."""
    payload = {"event": event, "ts": time.time(), **fields}
    print(f"EVENT: {json.dumps(payload)}", flush=True)


def _install_signal_handlers() -> None:
    """SIGTERM/SIGINT → exit cleanly so the OS reclaims memory."""
    def _handler(signo, _frame):
        logger.info("[eval-worker] received signal %s — exiting", signo)
        sys.exit(128 + signo)
    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description="Run lm-eval on one model in an isolated process.")
    parser.add_argument("--model", required=True, help="HF model id, e.g. meta-llama/Llama-3.2-3B-Instruct")
    parser.add_argument("--output", required=True, help="Path to write final JSON results")
    parser.add_argument("--adapter", default=None, help="Optional PEFT adapter path")
    parser.add_argument("--limit", type=int, default=None, help="Per-task sample limit (smoke tests)")
    parser.add_argument(
        "--benchmarks",
        default="mmlu,arc_challenge,hellaswag,gsm8k,humaneval",
        help="Comma-separated benchmark names from agents.eval_backend._TASK_CONFIG",
    )
    parser.add_argument(
        "--batch-size",
        default="16",
        help=(
            "Fixed batch size (int). Default 16 — safe on the 88 GiB cgroup "
            "for models up to 8B. lm-eval's `auto` mode is INTENTIONALLY "
            "disabled here because its doubling search (1→2→4→…→128) over-"
            "allocates and trips the cgroup OOM killer before PyTorch can "
            "catch the allocator failure (this killed the 3B smoke test on "
            "2026-05-08 with total-vm:311 GiB). For a 1B model bump to 32 "
            "for ~2x throughput; for 7B+ leave at 16."
        ),
    )
    args = parser.parse_args()

    _install_signal_handlers()

    # Required by lm-eval's HumanEval task; otherwise it refuses to score.
    os.environ.setdefault("HF_ALLOW_CODE_EVAL", "1")
    # Suppress noisy fork-warning that otherwise pollutes our JSONL stream.
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    # Pre-flight DRAM check — the campaign_runner gate already runs before us
    # but this belt-and-braces check covers manual `docker exec` invocations.
    try:
        from utils.memory_guard import check_memory
        check_memory(min_gb=10.0, label=f"eval-worker-start model={args.model}")
    except Exception as exc:
        print(f"[eval-worker] pre-flight DRAM check failed: {exc}", file=sys.stderr, flush=True)
        _emit("worker_error", phase="dram_preflight", error=str(exc))
        return 2

    # Import the canonical task config from the API module so we never drift
    # from the leaderboard-equivalent settings (instruct-task variants,
    # num_fewshot, gen_kwargs, requires_code_exec). PYTHONPATH=/app/src in
    # the Dockerfile makes this work inside the container.
    try:
        from agents.eval_backend import _TASK_CONFIG, _extract_lm_eval_score
    except ImportError as exc:
        print(f"[eval-worker] cannot import task config: {exc}", file=sys.stderr, flush=True)
        _emit("worker_error", phase="import", error=str(exc))
        return 2

    bench_list = [b.strip() for b in args.benchmarks.split(",") if b.strip()]
    is_instruct = any(t in args.model.lower() for t in ("instruct", "chat", "-it"))

    model_args = f"pretrained={args.model},dtype=bfloat16,trust_remote_code=True"
    if args.adapter:
        model_args += f",peft={args.adapter}"

    _emit(
        "worker_started",
        model=args.model,
        benchmarks=bench_list,
        instruct=is_instruct,
        limit=args.limit,
        adapter=args.adapter,
    )

    try:
        import lm_eval
    except ImportError as exc:
        print(f"[eval-worker] lm-eval not installed: {exc}", file=sys.stderr, flush=True)
        _emit("worker_error", phase="lm_eval_import", error=str(exc))
        return 2

    sig_params = set(inspect.signature(lm_eval.simple_evaluate).parameters.keys())

    t0 = time.perf_counter()

    # Load the HFLM ONCE and reuse across benchmarks. Passing model="hf" +
    # model_args to each simple_evaluate call would re-instantiate ~14 GB per
    # benchmark on a 7B; we only do that re-instantiation across processes.
    try:
        lm_obj = lm_eval.api.registry.get_model("hf").create_from_arg_string(
            model_args,
            {"batch_size": args.batch_size, "device": "cuda"},
        )
    except Exception as exc:
        print(f"[eval-worker] model load failed: {exc}", file=sys.stderr, flush=True)
        _emit("worker_error", phase="model_load", error=str(exc))
        return 2

    _emit("model_loaded", model=args.model, elapsed=time.perf_counter() - t0)

    scores: dict[str, float] = {}
    stderrs: dict[str, float] = {}
    failures: list[dict[str, Any]] = []

    for bench in bench_list:
        cfg = _TASK_CONFIG.get(bench)
        if not cfg:
            print(f"[eval-worker] unknown benchmark: {bench}", file=sys.stderr, flush=True)
            scores[bench] = 0.0
            stderrs[bench] = 0.0
            failures.append({"benchmark": bench, "error": "unknown benchmark"})
            continue

        task_id = cfg.get("instruct_task") if is_instruct and cfg.get("instruct_task") else cfg["task"]
        _emit("benchmark_started", benchmark=bench, task=task_id)

        kwargs: dict[str, Any] = dict(
            model=lm_obj,
            tasks=[task_id],
            num_fewshot=int(cfg["num_fewshot"]),
            batch_size=args.batch_size,
            device="cuda",
            limit=args.limit,
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

        bench_t0 = time.perf_counter()
        try:
            results = lm_eval.simple_evaluate(**kwargs)
            r = (results or {}).get("results", {}).get(task_id, {}) or {}
            score = _extract_lm_eval_score(bench, r)

            stderr = 0.0
            for sk in cfg.get("score_keys", ()):
                if "," in sk:
                    prefix, _, suffix = sk.partition(",")
                    stderr_key = f"{prefix}_stderr,{suffix}"
                else:
                    stderr_key = f"{sk}_stderr"
                v = r.get(stderr_key)
                if isinstance(v, (int, float)):
                    stderr = float(v)
                    break

            scores[bench] = float(score)
            stderrs[bench] = float(stderr)
            _emit(
                "benchmark_complete",
                benchmark=bench,
                task=task_id,
                score=float(score),
                stderr=float(stderr),
                elapsed=time.perf_counter() - bench_t0,
            )
        except Exception as exc:
            print(f"[eval-worker] {bench}/{task_id} failed: {exc}", file=sys.stderr, flush=True)
            scores[bench] = 0.0
            stderrs[bench] = 0.0
            failures.append({"benchmark": bench, "task": task_id, "error": str(exc)[:500]})
            _emit(
                "benchmark_complete",
                benchmark=bench,
                task=task_id,
                score=0.0,
                stderr=0.0,
                elapsed=time.perf_counter() - bench_t0,
                error=str(exc)[:200],
            )

    elapsed = time.perf_counter() - t0
    output = {
        "model": args.model,
        "adapter": args.adapter,
        "benchmarks": bench_list,
        "scores": scores,
        "stderrs": stderrs,
        "duration_seconds": elapsed,
        "failures": failures,
        "harness_version": getattr(lm_eval, "__version__", "unknown"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    try:
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
    except Exception as exc:
        print(f"[eval-worker] failed to write output: {exc}", file=sys.stderr, flush=True)
        _emit("worker_error", phase="output_write", error=str(exc))
        return 1

    _emit("worker_complete", scores=scores, duration=elapsed, output=args.output, failures=len(failures))
    return 3 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
