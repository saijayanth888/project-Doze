"""Training backend protocol + Mac (mock) and DGX (LoRA) implementations.

The real LoRA backend is imported lazily inside ``LoRATrainingBackend``
so the Mac dev image doesn't need ``torch`` / ``peft`` / ``trl``
wheels installed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger("modelforge.agents.training")


@dataclass
class TrainingResult:
    adapter_path: str | None
    method: str
    training_data_size: int
    duration_seconds: float


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
        return TrainingResult(
            adapter_path=f"adapters/{run_id}/gen-{generation}/adapter_model.safetensors",
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
        # Real LoRA training is a long-running, GPU-bound operation. We
        # delegate to a thread executor so the asyncio event loop stays
        # responsive (e.g. for /api/evolve/{run_id}/stop).
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._train_sync, run_id, generation, config)

    @staticmethod
    def _format_sample(example: dict) -> str:
        return (
            "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n"
            f"{example['question']}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
            f"{example['response']}<|eot_id|>"
        )

    def _train_sync(self, run_id: str, generation: int, config: dict) -> TrainingResult:
        import torch
        from datasets import load_dataset
        from peft import LoraConfig, PeftModel, get_peft_model
        from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
        from trl import SFTTrainer

        base_model = str(config.get("base_model") or "meta-llama/Llama-3.1-8B-Instruct")
        output_dir = f"data/adapters/{run_id}/gen-{generation}"
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
            guess = f"data/adapters/{run_id}/gen-{generation-1}"
            if os.path.isdir(guess):
                parent_adapter = guess

        if parent_adapter and os.path.isdir(str(parent_adapter)):
            logger.info("[lora-train] loading parent adapter: %s", parent_adapter)
            model = PeftModel.from_pretrained(model, str(parent_adapter))
            model = model.merge_and_unload()

        lora_cfg = LoraConfig(
            r=int(config.get("lora_rank", 16)),
            lora_alpha=int(config.get("lora_alpha", 32)),
            target_modules=list(config.get("target_modules") or ["q_proj", "v_proj", "k_proj", "o_proj"]),
            lora_dropout=float(config.get("lora_dropout", 0.05)),
            bias="none",
            task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, lora_cfg)

        raw = load_dataset("Open-Orca/OpenOrca", split="train[:1000]")
        dataset = raw.map(lambda ex: {"text": self._format_sample(ex)})

        bf16 = bool(torch.cuda.is_available() and getattr(torch.cuda, "is_bf16_supported", lambda: False)())
        args = TrainingArguments(
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
        )

        trainer = SFTTrainer(
            model=model,
            tokenizer=tokenizer,
            args=args,
            train_dataset=dataset,
            dataset_text_field="text",
            max_seq_length=int(config.get("max_seq_length", 512)),
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
