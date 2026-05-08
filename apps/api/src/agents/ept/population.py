"""EPT population manager — selection, crossover, mutation, survival.

Lifecycle (one EPT run)
-----------------------
1. ``initialize_population``: train K adapters from scratch on disjoint random
   data subsets so they start diverse, then evaluate.
2. For each generation:
   - ``_select_parents``  — top-N by avg score (rank selection).
   - ``_breed``           — for each parent pair, run crossover() in both
                            directions (A×B and B×A with the same alpha).
   - ``_mutate_children`` — short LoRA fine-tune on a fresh data subset to
                            give each child its own neighbourhood.
   - ``_evaluate``        — score each child on the eval benchmarks.
   - ``_survival``        — keep top K from (alive parents + children).
   - Snapshot state to disk.

Notes
-----
* Single-GPU host: members evaluate sequentially. Population gives **diversity**
  via crossover, not parallel speedup. Calling the existing eval/training
  backends keeps everything in lockstep.
* All heavy work runs in a thread executor so the event loop stays responsive
  for status polling / cancel requests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .crossover import CrossoverStrategy, crossover

logger = logging.getLogger("modelforge.ept.population")


@dataclass
class PopulationMember:
    member_id: str
    adapter_path: str
    generation: int
    scores: dict[str, float] = field(default_factory=dict)
    avg_score: float = 0.0
    parent_a: str | None = None
    parent_b: str | None = None
    crossover_alpha: float | None = None
    crossover_strategy: str | None = None
    mutation_steps: int = 0
    mutation_seconds: float = 0.0
    status: str = "alive"   # alive | eliminated | champion
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class PopulationConfig:
    population_size: int = 8
    num_parents: int = 4
    crossover_strategy: str = "uniform"
    mutation_steps: int = 50
    mutation_lr: float = 1e-4
    mutation_samples: int = 200
    alpha_min: float = 0.3
    alpha_max: float = 0.7
    max_generations: int = 20
    base_model: str = "meta-llama/Llama-3.2-3B-Instruct"
    target_benchmarks: list[str] = field(default_factory=lambda: ["arc_challenge", "hellaswag", "mmlu"])
    eval_benchmarks: list[str] = field(default_factory=lambda: ["arc_challenge", "hellaswag", "mmlu", "gsm8k"])
    lora_rank: int = 16
    lora_alpha: int = 32
    batch_size: int = 2
    seed: int | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PopulationConfig":
        kwargs = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**kwargs)


class PopulationManager:
    """Owns one EPT run's population + per-generation history."""

    def __init__(self, config: PopulationConfig, run_id: str | None = None, base_dir: str | None = None):
        self.config = config
        self.run_id = run_id or f"ept-{uuid.uuid4().hex[:8]}"
        self.population: list[PopulationMember] = []
        self.generation = 0
        self.history: list[dict[str, Any]] = []
        # Default base lives under data/ept/<run_id>/
        try:
            from config.settings import settings
            data_root = str(settings.resolve_data_root())
        except Exception:
            data_root = "data"
        self.base_dir = base_dir or os.path.join(data_root, "ept", self.run_id)
        os.makedirs(os.path.join(self.base_dir, "adapters"), exist_ok=True)
        if self.config.seed is not None:
            random.seed(self.config.seed)

    # ── Initialisation ───────────────────────────────────────────

    async def initialize_population(self, *, on_event=None) -> None:
        """Seed K diverse adapters from random training subsets."""
        from .mutation import mutate_adapter_subprocess  # heavy — lazy
        cfg = self.config
        await self._notify(on_event, "init", f"Initialising population of {cfg.population_size}")
        samples = await self._curate(cfg.mutation_samples * cfg.population_size, on_event=on_event)
        for i in range(cfg.population_size):
            mid = f"gen0-{i:03d}"
            adapter_path = os.path.join(self.base_dir, "adapters", mid)
            subset = random.sample(samples, min(cfg.mutation_samples, len(samples)))
            await self._notify(on_event, "init", f"Seeding {mid} ({len(subset)} samples, {cfg.mutation_steps} steps)")
            # Subprocess per member — each starts with a clean CUDA allocator.
            res = await mutate_adapter_subprocess(
                base_model=cfg.base_model,
                seed_adapter_path=None,
                samples=subset,
                output_dir=adapter_path,
                max_steps=cfg.mutation_steps,
                learning_rate=cfg.mutation_lr,
                batch_size=cfg.batch_size,
                lora_rank=cfg.lora_rank,
                lora_alpha=cfg.lora_alpha,
            )
            self.population.append(
                PopulationMember(
                    member_id=mid,
                    adapter_path=adapter_path,
                    generation=0,
                    mutation_steps=cfg.mutation_steps,
                    mutation_seconds=float(res.get("duration_sec") or 0.0),
                )
            )
        await self._evaluate_unscored(on_event=on_event)
        self._mark_champion()
        self._snapshot()

    # ── One generation ───────────────────────────────────────────

    async def evolve_generation(self, *, on_event=None) -> PopulationMember | None:
        """Run one EPT generation. Returns the new champion."""
        from .mutation import mutate_adapter_subprocess  # lazy
        self.generation += 1
        cfg = self.config
        await self._notify(on_event, f"gen{self.generation}", f"=== Generation {self.generation} ===")

        parents = self._select_parents()
        if len(parents) < 2:
            await self._notify(on_event, f"gen{self.generation}", "Not enough alive members to breed", level="warn")
            return self.get_champion()

        # ── Crossover ────────────────────────────────────────────
        children_paths: list[tuple[str, PopulationMember, PopulationMember, float]] = []
        for i in range(0, len(parents) - 1, 2):
            pa = parents[i]
            pb = parents[i + 1]
            alpha = random.uniform(cfg.alpha_min, cfg.alpha_max)
            child_a = crossover(
                pa.adapter_path, pb.adapter_path,
                output_dir=os.path.join(self.base_dir, "crossover"),
                alpha=alpha,
                strategy=CrossoverStrategy(cfg.crossover_strategy),
            )
            child_b = crossover(
                pb.adapter_path, pa.adapter_path,
                output_dir=os.path.join(self.base_dir, "crossover"),
                alpha=alpha,
                strategy=CrossoverStrategy(cfg.crossover_strategy),
            )
            children_paths.append((child_a, pa, pb, alpha))
            children_paths.append((child_b, pb, pa, alpha))
            await self._notify(
                on_event, f"gen{self.generation}",
                f"Crossover {pa.member_id} × {pb.member_id} α={alpha:.2f}",
            )

        # ── Mutation ─────────────────────────────────────────────
        samples = await self._curate(cfg.mutation_samples * len(children_paths), on_event=on_event)
        children: list[PopulationMember] = []
        for idx, (seed_path, pa, pb, alpha) in enumerate(children_paths):
            mid = f"gen{self.generation}-{idx:03d}"
            mutated_path = os.path.join(self.base_dir, "adapters", mid)
            subset = random.sample(samples, min(cfg.mutation_samples, len(samples)))
            await self._notify(
                on_event, f"gen{self.generation}",
                f"Mutating {mid} from {os.path.basename(seed_path)} ({cfg.mutation_steps} steps)",
            )
            # Subprocess per child — clean CUDA allocator each time.
            res = await mutate_adapter_subprocess(
                base_model=cfg.base_model,
                seed_adapter_path=seed_path,
                samples=subset,
                output_dir=mutated_path,
                max_steps=cfg.mutation_steps,
                learning_rate=cfg.mutation_lr,
                batch_size=cfg.batch_size,
                lora_rank=cfg.lora_rank,
                lora_alpha=cfg.lora_alpha,
            )
            children.append(
                PopulationMember(
                    member_id=mid,
                    adapter_path=mutated_path,
                    generation=self.generation,
                    parent_a=pa.member_id,
                    parent_b=pb.member_id,
                    crossover_alpha=alpha,
                    crossover_strategy=cfg.crossover_strategy,
                    mutation_steps=cfg.mutation_steps,
                    mutation_seconds=float(res.get("duration_sec") or 0.0),
                )
            )
        self.population.extend(children)

        # ── Evaluate the new children ────────────────────────────
        await self._evaluate_unscored(on_event=on_event)

        # ── Survival ─────────────────────────────────────────────
        alive = [m for m in self.population if m.status in ("alive", "champion")]
        alive.sort(key=lambda m: m.avg_score, reverse=True)
        survivors = alive[: cfg.population_size]
        kept_ids = {m.member_id for m in survivors}
        eliminated = 0
        for m in self.population:
            if m.status in ("eliminated",):
                continue
            if m.member_id not in kept_ids:
                m.status = "eliminated"
                eliminated += 1
            else:
                # Reset back to alive — the champion mark is reapplied next.
                m.status = "alive"
        self._mark_champion()
        champ = self.get_champion()
        champ_label = f"{champ.member_id} avg={champ.avg_score:.4f}" if champ else "n/a"
        await self._notify(
            on_event, f"gen{self.generation}",
            f"Survival — kept {len(survivors)} of {len(alive)} alive; eliminated {eliminated}. "
            f"Champion: {champ_label}",
        )
        self._snapshot()
        return champ

    # ── Selection / utilities ────────────────────────────────────

    def _select_parents(self) -> list[PopulationMember]:
        alive = [m for m in self.population if m.status in ("alive", "champion")]
        alive.sort(key=lambda m: m.avg_score, reverse=True)
        return alive[: self.config.num_parents]

    def _mark_champion(self) -> None:
        # Demote any current champion before re-electing.
        for m in self.population:
            if m.status == "champion":
                m.status = "alive"
        alive = [m for m in self.population if m.status == "alive"]
        if alive:
            best = max(alive, key=lambda m: m.avg_score)
            best.status = "champion"

    def get_champion(self) -> PopulationMember | None:
        for m in self.population:
            if m.status == "champion":
                return m
        # Fallback: highest scored alive member.
        alive = [m for m in self.population if m.status in ("alive", "champion")]
        return max(alive, key=lambda m: m.avg_score) if alive else None

    def get_lineage(self, member_id: str) -> list[str]:
        """Trace ancestry. Cycles are guarded against with a `visited` set."""
        by_id = {m.member_id: m for m in self.population}
        visited: set[str] = set()
        lineage: list[str] = []
        cur = by_id.get(member_id)
        while cur and cur.member_id not in visited:
            visited.add(cur.member_id)
            lineage.append(cur.member_id)
            cur = by_id.get(cur.parent_a or "") if cur.parent_a else None
        return list(reversed(lineage))

    # ── External integrations ────────────────────────────────────

    async def _curate(self, n: int, *, on_event=None) -> list[dict[str, Any]]:
        """Pull `n` HuggingFace samples for the configured target benchmarks.

        Reads back the curator's saved arrow shard so we can sample arbitrary
        subsets per member without re-pulling.
        """
        try:
            from services.data_curator import HuggingFaceDataCurator
            curator = HuggingFaceDataCurator()
        except Exception as exc:
            logger.warning("[ept] HF curator unavailable: %s — falling back to mock", exc)
            return [{"instruction": f"Q{i}", "response": f"A{i}"} for i in range(n)]

        await self._notify(on_event, "curate", f"Curating {n} samples from {self.config.target_benchmarks}")
        result = await curator.curate(
            weak_categories=self.config.target_benchmarks,
            weakness_report="EPT mutation pool",
            generation=self.generation,
            max_samples=int(n),
            config={"run_id": self.run_id},
        )
        try:
            from datasets import load_from_disk
            ds = load_from_disk(result.data_path)
            return list(ds)
        except Exception as exc:
            logger.warning("[ept] could not load curated dataset: %s", exc)
            return []

    async def _evaluate_unscored(self, *, on_event=None) -> None:
        """Run lm-eval on every member that doesn't have scores yet."""
        unscored = [m for m in self.population if not m.scores and m.status in ("alive", "champion")]
        if not unscored:
            return
        try:
            from agents.eval_backend import LMEvalHarnessBackend
            backend = LMEvalHarnessBackend()
        except Exception as exc:
            logger.warning("[ept] lm-eval backend unavailable (%s) — using uniform-zero scores", exc)
            for m in unscored:
                m.scores = {b: 0.0 for b in self.config.eval_benchmarks}
                m.avg_score = 0.0
            return
        for m in unscored:
            await self._notify(on_event, "eval", f"Evaluating {m.member_id}")
            try:
                result = await backend.evaluate(
                    run_id=self.run_id,
                    generation=m.generation,
                    adapter_path=m.adapter_path,
                    config={
                        "base_model": self.config.base_model,
                        "eval_benchmarks": self.config.eval_benchmarks,
                    },
                )
                m.scores = {k: float(v) for k, v in (result.scores or {}).items()}
                m.avg_score = sum(m.scores.values()) / max(1, len(m.scores))
            except Exception as exc:
                logger.warning("[ept] eval %s failed: %s — marking as zero", m.member_id, exc)
                m.scores = {b: 0.0 for b in self.config.eval_benchmarks}
                m.avg_score = 0.0

    @staticmethod
    async def _notify(on_event, phase: str, label: str, level: str = "info") -> None:
        if on_event is None:
            return
        try:
            await on_event({"phase": phase, "label": label, "level": level})
        except Exception:
            pass

    # ── Snapshot ────────────────────────────────────────────────

    def _snapshot(self) -> None:
        snapshot = {
            "generation": self.generation,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "champion": self._asdict(self.get_champion()),
            "population_alive": [self._asdict(m) for m in self.population if m.status in ("alive", "champion")],
            "newly_eliminated": [self._asdict(m) for m in self.population if m.status == "eliminated" and m.generation == self.generation - 1],
            "population_size": sum(1 for m in self.population if m.status in ("alive", "champion")),
        }
        self.history.append(snapshot)
        try:
            with open(os.path.join(self.base_dir, "history.json"), "w") as fh:
                json.dump(self.history, fh, indent=2)
            with open(os.path.join(self.base_dir, "population.json"), "w") as fh:
                json.dump([self._asdict(m) for m in self.population], fh, indent=2)
        except Exception as exc:
            logger.debug("snapshot write failed: %s", exc)

    @staticmethod
    def _asdict(m: PopulationMember | None) -> dict[str, Any] | None:
        return asdict(m) if m else None

    def serialize(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "generation": self.generation,
            "config": asdict(self.config),
            "population": [self._asdict(m) for m in self.population],
            "history_len": len(self.history),
        }
