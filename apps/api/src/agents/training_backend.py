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
from pathlib import Path
from typing import Protocol

from config.settings import settings
from utils.lora_targets import get_lora_target_modules

logger = logging.getLogger("modelforge.agents.training")


def _resolve_curated_path(curated_path: str | os.PathLike | None) -> Path | None:
    """Return the curated dataset directory if it exists and is rooted under
    the configured data root, else ``None``.

    Two guard rails:

    - **Path traversal**: the caller-supplied path must resolve (after
      symlink chasing) under ``settings.resolve_data_root()``. A request
      carrying ``curated_path="/etc/passwd"`` or
      ``curated_path="../../../etc"`` is rejected with a warning so the
      trainer falls back to the cold-start dataset rather than silently
      loading attacker-controlled bytes.
    - **Existence**: ``Path.exists()`` so a stale path from a missing
      generation also falls back instead of raising ``FileNotFoundError``
      inside ``load_from_disk``.
    """
    if not curated_path:
        return None
    try:
        cand = Path(curated_path).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        logger.warning("[curated-path] cannot resolve %r: %s", curated_path, exc)
        return None
    if not cand.exists():
        return None
    try:
        root = settings.resolve_data_root().resolve()
    except Exception as exc:  # pragma: no cover — settings failure is operator-visible
        logger.warning("[curated-path] cannot resolve data root: %s", exc)
        return None
    try:
        cand.relative_to(root)
    except ValueError:
        logger.warning(
            "[curated-path] rejected %s — not under configured data root %s",
            cand, root,
        )
        return None
    return cand


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
    # 10 MiB readline buffer: trl's training tqdm uses the same \r-update
    # pattern as lm-eval; default 64 KiB blows up on long fine-tunes.
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=10 * 1024 * 1024,
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
        # Accept any of the common SFT field aliases for the user-side text.
        # The HuggingFace curator emits `instruction`; OpenOrca and many
        # benchmark seed sets use `question`; trading-bot's modelforge_curate
        # also writes `instruction`. Falling back across the set makes the
        # trainer tolerant of dataset shape without requiring upstream
        # normalisation passes.
        user_text = (
            example.get("question")
            or example.get("instruction")
            or example.get("prompt")
            or example.get("user_message")
            or example.get("input")
            or ""
        )
        assistant_text = (
            example.get("response")
            or example.get("answer")
            or example.get("output")
            or example.get("completion")
            or ""
        )
        return (
            "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n"
            f"{user_text}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
            f"{assistant_text}<|eot_id|>"
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
        from datasets import load_dataset, load_from_disk
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

        # ── Device map: force single-device, no CPU offload ────────────
        # ``device_map="auto"`` lets accelerate split a model across GPU +
        # CPU (the "meta" device for offloaded params). On regular discrete-
        # GPU machines that lets bigger models fit; on GB10 unified-memory
        # hosts (CPU and GPU share one physical RAM pool) there is NO
        # benefit — and the split causes autograd to fail with
        #     "MmBackward0 returned an invalid gradient at index 1 —
        #      expected device meta but got cuda:0"
        # which we hit on 2026-05-17 at the very first backward pass of
        # the first sequential training attempt with Hermes-3-Llama-3.1-8B.
        # Force ``cuda:0`` so all params live on a single device. The
        # RAM precheck above (evolution.start action) already refused any
        # base model that wouldn't fit, so the OOM-vs-offload trade is
        # already won at the precheck layer.
        #
        # MODELFORGE_DEVICE_MAP env var lets the operator re-enable
        # multi-device splitting on hosts where that actually helps.
        device_map = os.environ.get("MODELFORGE_DEVICE_MAP", "cuda:0")
        model = AutoModelForCausalLM.from_pretrained(
            base_model,
            torch_dtype="auto",
            device_map=device_map,
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

        # PEFT's lora.ParamWrapper (used internally for MoE expert routing
        # weights — Qwen3-30B-A3B, Qwen3-Next-80B-A3B, deepseek-v2, Mixtral)
        # raises NotImplementedError when lora_dropout != 0:
        #     "lora.ParamWrapper does not work with lora_dropout != 0."
        # The default 0.05 dropout is fine on dense models (Llama, Qwen2.5
        # non-MoE, Phi, etc.) but trips this guard on every MoE base. Detect
        # by checking the resolved HF id for known MoE family markers and
        # force dropout to 0 in that case, with a logged WARNING so the
        # operator can see the override took effect.
        _lora_dropout = float(config.get("lora_dropout", 0.05))
        _bm_lower = str(base_model).lower()
        _MOE_MARKERS = ("a3b", "moe", "mixtral", "deepseek-v2", "deepseek-v3", "qwen3-next")
        if _lora_dropout != 0.0 and any(m in _bm_lower for m in _MOE_MARKERS):
            logger.warning(
                "[lora-train] base=%s is MoE; PEFT lora.ParamWrapper requires "
                "lora_dropout=0 (was %.3f). Overriding.",
                base_model, _lora_dropout,
            )
            _lora_dropout = 0.0

        lora_cfg = LoraConfig(
            r=int(config.get("lora_rank", 16)),
            lora_alpha=int(config.get("lora_alpha", 32)),
            target_modules=list(
                config.get("target_modules")
                or get_lora_target_modules(base_model)
            ),
            lora_dropout=_lora_dropout,
            bias="none",
            task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, lora_cfg)

        # Honor the curated dataset produced by data_curator + augment_training.
        # `curated_path` is set in evolution_graph.train_adapter before this call;
        # callers may also pass it directly when invoking the trainer outside the
        # graph (e.g. trading-bot integration). When absent or unsafe, fall back
        # to the OpenOrca cold-start dataset with a WARNING so the regression is
        # visible in logs.
        curated_path = config.get("curated_path") or config.get("training_data_path")
        safe_curated = _resolve_curated_path(curated_path)
        if safe_curated is not None:
            logger.info("[lora-train] loading curated dataset from %s", safe_curated)
            raw = load_from_disk(str(safe_curated))
        else:
            if curated_path:
                logger.warning(
                    "[lora-train] curated_path=%r unusable (missing or outside data root); "
                    "falling back to OpenOrca cold-start dataset",
                    curated_path,
                )
            else:
                logger.warning(
                    "[lora-train] no curated_path provided; "
                    "falling back to OpenOrca cold-start dataset"
                )
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
