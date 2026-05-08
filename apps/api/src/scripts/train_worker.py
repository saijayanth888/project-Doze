#!/usr/bin/env python3
"""Train worker — runs ONE LoRA fine-tune in an isolated process.

Spawned by LoRATrainingBackend.train() (sequential evolution) and by
mutate_worker.py (EPT mutation). Same rationale as eval_worker.py:
in-process gc + cuda.empty_cache() leak 1-5 GB per generation, which
on a 5-gen sequential run accumulates into the unified-memory freeze
fingerprinted in the project_dgx_freeze_fingerprint memory.

Output channels:
- stdout: JSONL progress events prefixed `EVENT: `. The Redis-publishing
  metrics callback (used by the dashboard's training-progress widget)
  still works from inside this subprocess because the subprocess inherits
  the container's network namespace and reaches `redis://redis:6379`.
- stderr: trl/transformers tqdm + tracebacks (forwarded to docker logs).
- final results JSON at `--output`: adapter_path + duration + sample count.

Exit codes:
- 0   training succeeded, adapter saved, output JSON written
- 1   write-output error
- 2   setup / model load error
- 3   training error (output may not be written)
- 130 SIGINT/SIGTERM (force_stop from parent)
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from typing import Any

logger = logging.getLogger("train-worker")


def _emit(event: str, **fields: Any) -> None:
    payload = {"event": event, "ts": time.time(), **fields}
    print(f"EVENT: {json.dumps(payload)}", flush=True)


def _install_signal_handlers() -> None:
    def _handler(signo, _frame):
        logger.info("[train-worker] received signal %s — exiting", signo)
        sys.exit(128 + signo)
    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description="Run one LoRA fine-tune in an isolated process.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--config", required=True, help="JSON-encoded training config dict")
    parser.add_argument("--output", required=True, help="Path to write final result JSON")
    args = parser.parse_args()

    _install_signal_handlers()

    try:
        config = json.loads(args.config)
    except json.JSONDecodeError as exc:
        print(f"[train-worker] bad --config JSON: {exc}", file=sys.stderr, flush=True)
        return 2

    _emit("worker_started", run_id=args.run_id, generation=args.generation, base_model=config.get("base_model"))

    # _train_sync_inner already runs check_memory(min_gb=15.0) at the top.
    try:
        from agents.training_backend import LoRATrainingBackend
    except ImportError as exc:
        print(f"[train-worker] cannot import LoRATrainingBackend: {exc}", file=sys.stderr, flush=True)
        _emit("worker_error", phase="import", error=str(exc))
        return 2

    try:
        backend = LoRATrainingBackend()
    except RuntimeError as exc:
        # Raised when torch/peft/trl aren't installed (mac dev path).
        print(f"[train-worker] backend init failed: {exc}", file=sys.stderr, flush=True)
        _emit("worker_error", phase="backend_init", error=str(exc))
        return 2

    t0 = time.perf_counter()
    try:
        result = backend._train_sync_inner(args.run_id, args.generation, config)
    except Exception as exc:
        print(f"[train-worker] training failed: {exc}", file=sys.stderr, flush=True)
        _emit("worker_error", phase="train", error=str(exc)[:500])
        return 3

    elapsed = time.perf_counter() - t0
    output = {
        "run_id": args.run_id,
        "generation": args.generation,
        "adapter_path": result.adapter_path,
        "method": result.method,
        "training_data_size": result.training_data_size,
        "duration_seconds": result.duration_seconds,
        "wall_seconds": elapsed,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    try:
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
    except OSError as exc:
        print(f"[train-worker] failed to write output: {exc}", file=sys.stderr, flush=True)
        _emit("worker_error", phase="output_write", error=str(exc))
        return 1

    _emit(
        "worker_complete",
        adapter_path=result.adapter_path,
        training_data_size=result.training_data_size,
        duration=result.duration_seconds,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
