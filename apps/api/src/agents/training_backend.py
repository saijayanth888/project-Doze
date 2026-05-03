"""Training backend protocol + Mac (mock) and DGX (LoRA) implementations.

The real LoRA backend is imported lazily inside ``LoRATrainingBackend``
so the Mac dev image doesn't need ``torch`` / ``peft`` / ``trl``
wheels installed.
"""

from __future__ import annotations

import asyncio
import logging
import random
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

    def _train_sync(self, run_id: str, generation: int, config: dict) -> TrainingResult:
        # Concrete LoRA training intentionally left as a stub: hooking
        # this up to PEFT + TRL on the DGX requires base-model weights,
        # tokeniser, dataset path, and accelerator config that depend on
        # the deployment. The mock backend provides a faithful interface
        # that the rest of the graph treats identically.
        raise NotImplementedError(
            "LoRATrainingBackend._train_sync must be wired up to your "
            "PEFT + TRL pipeline before deploying to DGX Spark."
        )
