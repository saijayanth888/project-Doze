"""EPT mutation — short LoRA fine-tune that perturbs an existing adapter.

The population manager calls this after crossover so each child explores its
own neighbourhood in weight space. Default is 50 steps on 200 samples — fast
enough that a population of 8 children evolves in minutes per generation,
not hours.

Implemented as a self-contained sync function (heavy imports inside) so it
can run inside ``loop.run_in_executor`` without keeping torch on the API
process's import path during cold start.
"""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import os
import random
import shutil
import tempfile
import time
import uuid
from typing import Any

logger = logging.getLogger("modelforge.ept.mutation")


# ── Mutate subprocess runner ────────────────────────────────────
_MUTATE_WORKER_SCRIPT = "/app/src/scripts/mutate_worker.py"


async def mutate_adapter_subprocess(
    *,
    base_model: str,
    seed_adapter_path: str | None,
    samples: list[dict[str, Any]],
    output_dir: str,
    max_steps: int = 50,
    learning_rate: float = 1e-4,
    batch_size: int = 2,
    lora_rank: int = 16,
    lora_alpha: int = 32,
    max_seq_length: int = 512,
) -> dict[str, Any]:
    """Spawn mutate_worker.py for ONE EPT mutation. Subprocess isolation
    means each population member's mutation starts with a clean CUDA
    allocator — critical because EPT does N mutations per generation and
    in-process leaks accumulate fast on a population_size>=4 run."""
    samples_path = os.path.join(tempfile.gettempdir(), f"mut-samples-{uuid.uuid4().hex[:8]}.json")
    result_path = os.path.join(tempfile.gettempdir(), f"mut-result-{uuid.uuid4().hex[:8]}.json")
    with open(samples_path, "w") as f:
        json.dump(samples, f)

    cmd = [
        "python",
        _MUTATE_WORKER_SCRIPT,
        "--base-model", base_model,
        "--samples", samples_path,
        "--output-dir", output_dir,
        "--max-steps", str(max_steps),
        "--learning-rate", str(learning_rate),
        "--batch-size", str(batch_size),
        "--lora-rank", str(lora_rank),
        "--lora-alpha", str(lora_alpha),
        "--max-seq-length", str(max_seq_length),
        "--result-json", result_path,
    ]
    if seed_adapter_path:
        cmd.extend(["--seed-adapter", seed_adapter_path])

    logger.info("[mutate-subprocess] spawn out=%s seed=%s", output_dir, seed_adapter_path)

    # argv-list spawn (no shell, no injection); inputs are config-driven.
    # 10 MiB readline buffer: tqdm output uses \r updates that accumulate
    # past 64 KiB during long mutations; default would raise LimitOverrunError.
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=10 * 1024 * 1024,
    )

    async def _consume(stream, prefix):
        if stream is None:
            return
        while True:
            b = await stream.readline()
            if not b:
                return
            line = b.decode(errors="replace").rstrip()
            if line:
                logger.info("[mutate-worker %s] %s", prefix, line)

    try:
        await asyncio.gather(_consume(proc.stdout, "stdout"), _consume(proc.stderr, "stderr"), proc.wait())
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
    finally:
        try:
            os.unlink(samples_path)
        except OSError:
            pass

    rc = proc.returncode
    if rc != 0:
        try:
            os.unlink(result_path)
        except OSError:
            pass
        raise RuntimeError(f"mutate-worker exited with code {rc}")

    try:
        with open(result_path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"mutate-worker output unreadable: {exc}") from exc
    finally:
        try:
            os.unlink(result_path)
        except OSError:
            pass


def _format_sample(ex: dict[str, Any]) -> str:
    """Same template the main training_backend uses, kept self-contained
    so EPT doesn't pull in agents.training_backend (and torch) at import time."""
    instr = str(ex.get("instruction") or ex.get("question") or ex.get("text") or "").strip()
    resp = str(ex.get("response") or ex.get("output") or ex.get("answer") or "").strip()
    return (
        "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n"
        f"{instr}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
        f"{resp}<|eot_id|>"
    )


def mutate_adapter(
    *,
    base_model: str,
    seed_adapter_path: str | None,
    samples: list[dict[str, Any]],
    output_dir: str,
    max_steps: int = 50,
    learning_rate: float = 1e-4,
    batch_size: int = 2,
    lora_rank: int = 16,
    lora_alpha: int = 32,
    max_seq_length: int = 512,
) -> dict[str, Any]:
    """Apply ``max_steps`` of LoRA fine-tuning on ``samples``, starting from
    ``seed_adapter_path`` (or a fresh PEFT init if None). Saves to
    ``output_dir`` and returns a summary dict.

    Wrapped in try/finally for CUDA cleanup so a member's mutation can't
    poison the next member with stale allocator state.
    """
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, PeftModel, get_peft_model
        from utils.lora_targets import get_lora_target_modules
        from utils.memory_guard import check_memory
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from trl import SFTConfig, SFTTrainer

        check_memory(min_gb=12.0, label=f"pre-mutation out={os.path.basename(output_dir)}")

        # Resolve any Ollama-tag base into a HF id.
        try:
            from utils.hf_model_id import resolve_hf_base_model_id
            base_id = resolve_hf_base_model_id(base_model)
        except Exception:
            base_id = base_model

        os.makedirs(output_dir, exist_ok=True)
        t0 = time.perf_counter()

        logger.info(
            "[mutate] base=%s seed=%s out=%s steps=%d samples=%d",
            base_id,
            os.path.basename(seed_adapter_path) if seed_adapter_path else "(none)",
            os.path.basename(output_dir), max_steps, len(samples),
        )

        tok = AutoTokenizer.from_pretrained(base_id, use_fast=True)
        if tok.pad_token is None:
            tok.pad_token = tok.eos_token

        dtype = (
            torch.bfloat16
            if torch.cuda.is_available() and torch.cuda.is_bf16_supported()
            else torch.float16
        )
        model = AutoModelForCausalLM.from_pretrained(
            base_id, torch_dtype=dtype, device_map="auto" if torch.cuda.is_available() else None,
        )

        # Crossover gives us a child adapter; mutation should *continue*
        # training those LoRA matrices in-place rather than baking them into
        # the base and starting a fresh adapter. Otherwise the only thing
        # passed from one generation to the next is the base + (now merged)
        # crossover, and the new mutation LoRA is independent — defeating
        # the point of population evolution.
        #
        # The conventional way to do this is `is_trainable=True` on
        # PeftModel.from_pretrained. SFTTrainer's optimiser will then
        # update the existing LoRA tensors, and save_pretrained writes the
        # *evolved* adapter (NOT a brand-new one). When there's no seed,
        # we fall through to a fresh PEFT init via get_peft_model.
        used_seed = False
        if seed_adapter_path and os.path.isdir(seed_adapter_path):
            try:
                model = PeftModel.from_pretrained(
                    model, seed_adapter_path, is_trainable=True,
                )
                used_seed = True
            except Exception as exc:
                logger.warning(
                    "[mutate] could not load seed adapter (%s) — falling back to fresh PEFT init",
                    exc,
                )

        if not used_seed:
            lora_cfg = LoraConfig(
                r=int(lora_rank),
                lora_alpha=int(lora_alpha),
                target_modules=get_lora_target_modules(base_id),
                lora_dropout=0.05,
                bias="none",
                task_type="CAUSAL_LM",
            )
            model = get_peft_model(model, lora_cfg)

        # Build dataset — small, tokenised at SFTTrainer time.
        ds = Dataset.from_list([{"text": _format_sample(ex)} for ex in samples])

        bf16 = bool(torch.cuda.is_available() and torch.cuda.is_bf16_supported())
        args = SFTConfig(
            output_dir=output_dir,
            max_steps=int(max_steps),
            per_device_train_batch_size=int(batch_size),
            gradient_accumulation_steps=2,
            learning_rate=float(learning_rate),
            bf16=bf16,
            fp16=not bf16,
            logging_steps=10,
            save_strategy="no",
            report_to=[],
            dataset_text_field="text",
            max_length=int(max_seq_length),
        )
        trainer = SFTTrainer(
            model=model,
            processing_class=tok,
            args=args,
            train_dataset=ds,
        )
        trainer.train()

        model.save_pretrained(output_dir)
        tok.save_pretrained(output_dir)

        # Drop a small marker so the population manager can recognise this as
        # an EPT-mutated adapter even after a process restart.
        with open(os.path.join(output_dir, "ept_mutation.json"), "w") as fh:
            json.dump(
                {
                    "kind": "ept_mutation",
                    "base_model": base_id,
                    "seed_adapter_path": seed_adapter_path,
                    "max_steps": int(max_steps),
                    "learning_rate": float(learning_rate),
                    "sample_count": len(samples),
                },
                fh, indent=2,
            )

        duration = time.perf_counter() - t0
        logger.info("[mutate] done in %.1fs → %s", duration, output_dir)
        return {
            "adapter_path": output_dir,
            "duration_sec": float(duration),
            "max_steps": int(max_steps),
            "sample_count": len(samples),
        }
    finally:
        try:
            import torch as _torch
            if _torch.cuda.is_available():
                _torch.cuda.empty_cache()
                if hasattr(_torch.cuda, "ipc_collect"):
                    _torch.cuda.ipc_collect()
        except Exception:
            pass
        gc.collect()
