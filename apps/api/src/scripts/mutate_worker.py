#!/usr/bin/env python3
"""Mutate worker — runs ONE EPT adapter mutation in an isolated process.

Spawned by the EPT population manager. Each mutation = a short LoRA fine-tune
(default 50 steps on 200 samples) seeded from a parent adapter. We isolate
each mutation in its own process so a population_size=8 generation doesn't
leak 8x model loads into one process — which on a 7B base would silently
exhaust unified memory by generation 2.

Same JSONL stdout protocol + final-results-JSON contract as eval_worker.py /
train_worker.py.

Exit codes:
- 0   mutation succeeded, adapter saved, output JSON written
- 1   write-output error
- 2   setup error
- 3   mutation error
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

logger = logging.getLogger("mutate-worker")


def _emit(event: str, **fields: Any) -> None:
    payload = {"event": event, "ts": time.time(), **fields}
    print(f"EVENT: {json.dumps(payload)}", flush=True)


def _install_signal_handlers() -> None:
    def _handler(signo, _frame):
        logger.info("[mutate-worker] received signal %s — exiting", signo)
        sys.exit(128 + signo)
    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description="Run one EPT adapter mutation in an isolated process.")
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--seed-adapter", default=None, help="Parent adapter dir (None = fresh PEFT init)")
    parser.add_argument("--samples", required=True, help="Path to JSON file with list of training samples")
    parser.add_argument("--output-dir", required=True, help="Where to save the new adapter")
    parser.add_argument("--max-steps", type=int, default=50)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--lora-rank", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--max-seq-length", type=int, default=512)
    parser.add_argument("--result-json", required=True, help="Path to write the result summary JSON")
    args = parser.parse_args()

    _install_signal_handlers()

    try:
        with open(args.samples) as f:
            samples = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[mutate-worker] cannot read samples file: {exc}", file=sys.stderr, flush=True)
        return 2

    _emit(
        "worker_started",
        base_model=args.base_model,
        seed_adapter=args.seed_adapter,
        n_samples=len(samples),
        max_steps=args.max_steps,
        output_dir=args.output_dir,
    )

    try:
        from agents.ept.mutation import mutate_adapter
    except ImportError as exc:
        print(f"[mutate-worker] cannot import mutate_adapter: {exc}", file=sys.stderr, flush=True)
        _emit("worker_error", phase="import", error=str(exc))
        return 2

    t0 = time.perf_counter()
    try:
        summary = mutate_adapter(
            base_model=args.base_model,
            seed_adapter_path=args.seed_adapter,
            samples=samples,
            output_dir=args.output_dir,
            max_steps=args.max_steps,
            learning_rate=args.learning_rate,
            batch_size=args.batch_size,
            lora_rank=args.lora_rank,
            lora_alpha=args.lora_alpha,
            max_seq_length=args.max_seq_length,
        )
    except Exception as exc:
        print(f"[mutate-worker] mutation failed: {exc}", file=sys.stderr, flush=True)
        _emit("worker_error", phase="mutate", error=str(exc)[:500])
        return 3

    elapsed = time.perf_counter() - t0
    summary = dict(summary or {})
    summary["wall_seconds"] = elapsed
    summary["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        with open(args.result_json, "w") as f:
            json.dump(summary, f, indent=2)
    except OSError as exc:
        print(f"[mutate-worker] failed to write result JSON: {exc}", file=sys.stderr, flush=True)
        _emit("worker_error", phase="output_write", error=str(exc))
        return 1

    _emit("worker_complete", output_dir=args.output_dir, duration=elapsed, summary=summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
