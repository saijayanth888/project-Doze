"""Training backend protocol + Mac (mock) and DGX (LoRA) implementations.

The real LoRA backend is imported lazily inside ``LoRATrainingBackend``
so the Mac dev image doesn't need ``torch`` / ``peft`` / ``trl``
wheels installed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Protocol

from config.settings import settings
from utils.lora_targets import get_lora_target_modules

logger = logging.getLogger("modelforge.agents.training")


@dataclass
class TrainingResult:
    adapter_path: str | None
    method: str
    training_data_size: int
    duration_seconds: float


# ── Train subprocess runner ─────────────────────────────────────
_TRAIN_WORKER_SCRIPT = "/app/src/scripts/train_worker.py"


async def _run_train_subprocess(run_id: str, generation: int, config: dict) -> "TrainingResult":
    """Spawn train_worker.py and return the result. Subprocess isolation
    means every generation starts with a fresh CUDA allocator state."""
    import uuid as _uuid
    output_path = f"/tmp/train-{run_id}-{generation}-{_uuid.uuid4().hex[:6]}.json"
    cmd = [
        "python",
        _TRAIN_WORKER_SCRIPT,
        "--run-id", run_id,
        "--generation", str(generation),
        "--config", json.dumps(config),
        "--output", output_path,
    ]
    logger.info("[lora-train] spawning train-worker for run=%s gen=%d", run_id, generation)

    # argv-list spawn (no shell, no injection); cmd values are config-driven.
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _consume_stdout() -> None:
        assert proc.stdout is not None
        while True:
            b = await proc.stdout.readline()
            if not b:
                return
            line = b.decode(errors="replace").rstrip()
            if line:
                logger.info("[train-worker stdout] %s", line)

    async def _consume_stderr() -> None:
        assert proc.stderr is not None
        while True:
            b = await proc.stderr.readline()
            if not b:
                return
            line = b.decode(errors="replace").rstrip()
            if line:
                logger.info("[train-worker stderr] %s", line)

    try:
        await asyncio.gather(_consume_stdout(), _consume_stderr(), proc.wait())
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
            except Exception:
                pass
        raise

    rc = proc.returncode
    if rc != 0:
        try:
            os.unlink(output_path)
        except OSError:
            pass
        raise RuntimeError(f"train-worker exited with code {rc}")

    try:
        with open(output_path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"train-worker output unreadable: {exc}") from exc
    finally:
        try:
            os.unlink(output_path)
        except OSError:
            pass

    return TrainingResult(
        adapter_path=data.get("adapter_path"),
        method=data.get("method", "lora"),
        training_data_size=int(data.get("training_data_size") or 0),
        duration_seconds=float(data.get("duration_seconds") or 0.0),
    )


class TrainingBackend(Protocol):
    name: str

    async def train(self, *, run_id: str, generation: int, config: dict) -> TrainingResult: ...


# ── Mock (Mac dev) ───────────────────────────────────────────────
class MockTrainingBackend:
    name = "mock"

    def __init__(self, sleep_s: float = 0.5) -> None:
        self._sleep_s = sleep_s

    async def train(self, *, run_id: str, generation: int, config: dict) -> TrainingResult:
        logger.info("[mock-train] run=%s gen=%d sleep=%.2fs", run_id, generation, self._sleep_s)
        await asyncio.sleep(self._sleep_s)
        out = (
            settings.resolve_data_root() / "adapters" / run_id / f"gen-{generation}"
        )
        out.mkdir(parents=True, exist_ok=True)
        return TrainingResult(
            adapter_path=str(out / "adapter_model.safetensors"),
            method="lora",
            training_data_size=random.randint(800, 1200),
            duration_seconds=self._sleep_s,
        )


# ── Real LoRA (DGX Spark) ────────────────────────────────────────
class LoRATrainingBackend:
    name = "lora"

    def __init__(self) -> None:
        # Defer heavy imports until the backend is actually selected.
        try:
            import peft  # noqa: F401
            import torch  # noqa: F401
            import trl  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "LoRATrainingBackend requires `torch`, `peft`, and `trl`. "
                "Install via `pip install -r requirements.txt[gpu]` on DGX Spark."
            ) from exc

    async def train(self, *, run_id: str, generation: int, config: dict) -> TrainingResult:
        """Run LoRA training in a fresh subprocess.

        Subprocess isolation is required on the DGX Spark unified-memory
        architecture: in-process gc + cuda.empty_cache() leak 1-5 GB per
        generation, which over a 5-gen sequential run silently freezes the
        host (NVRM `_memdescAllocInternal` OOM, see project_dgx_freeze_
        fingerprint memory). Process exit reclaims everything atomically.
        """
        return await _run_train_subprocess(run_id, generation, config)

    @staticmethod
    def _format_sample(example: dict) -> str:
        return (
            "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n"
            f"{example['question']}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
            f"{example['response']}<|eot_id|>"
        )

    def _train_sync(self, run_id: str, generation: int, config: dict) -> TrainingResult:
        try:
            return self._train_sync_inner(run_id, generation, config)
        finally:
            # Always release CUDA allocator state so a failed run does not poison the next one.
            # Without this, a long-running API process accumulates "fragmented" allocations and
            # eventually OOMs on a checkpoint that would otherwise fit (especially on shared
            # unified-memory hardware like DGX Spark).
            import gc
            gc.collect()
            try:
                import torch as _torch  # local import: torch may not even be importable here
                if _torch.cuda.is_available():
                    _torch.cuda.empty_cache()
                    if hasattr(_torch.cuda, "ipc_collect"):
                        _torch.cuda.ipc_collect()
            except Exception as exc:
                logger.debug("[lora-train] cuda cleanup skipped: %s", exc)

    def _train_sync_inner(self, run_id: str, generation: int, config: dict) -> TrainingResult:
        import redis
        import torch
        from datasets import load_dataset
        from peft import LoraConfig, PeftModel, get_peft_model
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            TrainerCallback,
        )
        from trl import SFTConfig, SFTTrainer

        from utils.memory_guard import check_memory
        # Refuse to start a LoRA fine-tune if DRAM is already too low —
        # cheaper to fail fast than to wedge the host on a unified-memory box.
        check_memory(min_gb=15.0, label=f"pre-training run={run_id} gen={generation}")

        class _RedisMetricsCallback(TrainerCallback):
            def __init__(self, rid: str) -> None:
                self._run_id = rid
                self._r = redis.Redis.from_url(settings.redis_url, decode_responses=True)

            def on_log(self, args, state, control, logs=None, **kwargs):
                if logs is None:
                    return
                tps = 0.0
                tss = logs.get("train_samples_per_second")
                if tss is not None:
                    tps = float(tss) * 100.0
                payload = {
                    "step": int(getattr(state, "global_step", 0) or 0),
                    "loss": float(logs.get("loss") or 0),
                    "lr": float(logs.get("learning_rate") or 0),
                    "epoch": float(logs.get("epoch") or 0),
                    "tokens_per_sec": tps,
                }
                try:
                    self._r.publish(f"training:{self._run_id}", json.dumps(payload))
                except Exception as exc:
                    logger.debug("redis publish skip: %s", exc)

            def on_train_end(self, args, state, control, **kwargs):
                try:
                    self._r.publish(f"training:{self._run_id}", json.dumps({"event": "done"}))
                except Exception:
                    pass

        from utils.hf_model_id import resolve_hf_base_model_id

        raw_bm = config.get("base_model")
        base_model = resolve_hf_base_model_id(
            str(raw_bm).strip() if raw_bm else None,
        )
        dr = settings.resolve_data_root()
        output_dir = str(dr / "adapters" / run_id / f"gen-{generation}")
        os.makedirs(output_dir, exist_ok=True)

        t0 = time.perf_counter()
        logger.info("[lora-train] run=%s gen=%d base=%s out=%s", run_id, generation, base_model, output_dir)

        model = AutoModelForCausalLM.from_pretrained(
            base_model,
            torch_dtype="auto",
            device_map="auto",
        )
        tokenizer = AutoTokenizer.from_pretrained(base_model, use_fast=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        # Parent adapter: explicit in config or previous generation's adapter dir (if present).
        parent_adapter = config.get("parent_adapter_path")
        if not parent_adapter and generation > 1:
            guess = str(dr / "adapters" / run_id / f"gen-{generation-1}")
            if os.path.isdir(guess):
                parent_adapter = guess

        if parent_adapter and os.path.isdir(str(parent_adapter)):
            logger.info("[lora-train] loading parent adapter: %s", parent_adapter)
            model = PeftModel.from_pretrained(model, str(parent_adapter))
            model = model.merge_and_unload()

        lora_cfg = LoraConfig(
            r=int(config.get("lora_rank", 16)),
            lora_alpha=int(config.get("lora_alpha", 32)),
            target_modules=list(
                config.get("target_modules")
                or get_lora_target_modules(base_model)
            ),
            lora_dropout=float(config.get("lora_dropout", 0.05)),
            bias="none",
            task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, lora_cfg)

        raw = load_dataset("Open-Orca/OpenOrca", split="train[:1000]")
        dataset = raw.map(lambda ex: {"text": self._format_sample(ex)})

        bf16 = bool(torch.cuda.is_available() and getattr(torch.cuda, "is_bf16_supported", lambda: False)())
        # trl >= 0.12 moved dataset_text_field / max_seq_length onto SFTConfig
        # (which subclasses transformers.TrainingArguments). Older
        # `SFTTrainer(..., dataset_text_field=..., max_seq_length=...)` calls now
        # raise TypeError.
        args = SFTConfig(
            output_dir=output_dir,
            num_train_epochs=float(config.get("num_epochs", 1)),
            per_device_train_batch_size=int(config.get("batch_size", 2)),
            gradient_accumulation_steps=int(config.get("gradient_accumulation_steps", 4)),
            learning_rate=float(config.get("learning_rate", 2e-4)),
            bf16=bf16,
            fp16=not bf16,
            logging_steps=10,
            save_strategy="no",
            report_to=[],
            dataset_text_field="text",
            # trl >= 1.x renamed `max_seq_length` to `max_length` on SFTConfig.
            max_length=int(config.get("max_seq_length") or config.get("max_length") or 512),
        )

        trainer = SFTTrainer(
            model=model,
            processing_class=tokenizer,
            args=args,
            train_dataset=dataset,
            callbacks=[_RedisMetricsCallback(run_id)],
        )
        trainer.train()

        model.save_pretrained(output_dir)
        tokenizer.save_pretrained(output_dir)

        elapsed = time.perf_counter() - t0
        logger.info("[lora-train] run=%s gen=%d adapter saved to %s (%.1fs)", run_id, generation, output_dir, elapsed)
        return TrainingResult(
            adapter_path=output_dir,
            method="lora",
            training_data_size=len(dataset),
            duration_seconds=float(elapsed),
        )
