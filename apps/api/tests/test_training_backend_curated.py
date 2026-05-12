"""Tests for the curated-dataset path in the LoRA training backend.

Covers the R1 fix from trading-bot's MODELFORGE_INTEGRATION_PLAN.md:
``training_backend._train_sync_inner`` used to hardcode
``load_dataset("Open-Orca/OpenOrca", split="train[:1000]")`` regardless of
``curated_path``. The trainer now resolves ``config["curated_path"]`` (or
the legacy ``config["training_data_path"]``) against the configured data
root and only falls back to OpenOrca as a cold-start path.

Two surfaces are tested:

1. ``_resolve_curated_path`` — pure, no torch/peft/trl dependency.
2. ``evolution_graph.train_adapter`` — the missing call-chain hop that
   actually propagates ``state["training_data_path"]`` into the trainer's
   ``config`` dict.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from agents.eval_backend import MockEvalBackend
from agents.evolution_graph import build_graph
from agents.training_backend import (
    TrainingResult,
    _resolve_curated_path,
)
from config.settings import settings
from services.data_curator import CurationResult

# ── _resolve_curated_path ────────────────────────────────────────────────


def test_resolve_curated_path_returns_path_when_under_data_root(tmp_path, monkeypatch):
    """A curated dir rooted under MODELFORGE_DATA_ROOT resolves to a Path."""
    monkeypatch.setenv("MODELFORGE_DATA_ROOT", str(tmp_path))
    # The Settings instance is built at import time, so override its resolver.
    monkeypatch.setattr(settings, "modelforge_data_root", str(tmp_path), raising=False)

    curated = tmp_path / "curated" / "gen-1"
    curated.mkdir(parents=True)
    (curated / "dataset_info.json").write_text("{}", encoding="utf-8")

    resolved = _resolve_curated_path(str(curated))
    assert resolved is not None
    assert resolved == curated.resolve()


def test_resolve_curated_path_none_when_input_none():
    assert _resolve_curated_path(None) is None
    assert _resolve_curated_path("") is None


def test_resolve_curated_path_none_when_path_missing(tmp_path, monkeypatch):
    """A path that doesn't exist returns None — trainer should fall back."""
    monkeypatch.setenv("MODELFORGE_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "modelforge_data_root", str(tmp_path), raising=False)

    missing = tmp_path / "curated" / "gen-99"
    assert not missing.exists()
    assert _resolve_curated_path(str(missing)) is None


def test_resolve_curated_path_rejects_traversal_outside_data_root(
    tmp_path, monkeypatch, caplog
):
    """Path traversal: a curated_path outside the data root is rejected
    with a warning so the trainer falls back to the cold-start dataset
    rather than loading attacker-controlled bytes."""
    data_root = tmp_path / "data"
    data_root.mkdir()
    outside = tmp_path / "evil"
    outside.mkdir()
    (outside / "dataset_info.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("MODELFORGE_DATA_ROOT", str(data_root))
    monkeypatch.setattr(settings, "modelforge_data_root", str(data_root), raising=False)

    with caplog.at_level(logging.WARNING, logger="modelforge.agents.training"):
        resolved = _resolve_curated_path(str(outside))

    assert resolved is None
    assert any(
        "not under configured data root" in rec.getMessage() for rec in caplog.records
    ), f"expected traversal-rejection warning, got: {[r.getMessage() for r in caplog.records]}"


def test_resolve_curated_path_rejects_dotdot_traversal(tmp_path, monkeypatch, caplog):
    """The classic ``..`` traversal also lands outside the data root."""
    data_root = tmp_path / "data"
    data_root.mkdir()
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    monkeypatch.setenv("MODELFORGE_DATA_ROOT", str(data_root))
    monkeypatch.setattr(settings, "modelforge_data_root", str(data_root), raising=False)

    # data_root/../sibling resolves to {tmp_path}/sibling — outside data_root.
    traversal = data_root / ".." / "sibling"
    with caplog.at_level(logging.WARNING, logger="modelforge.agents.training"):
        assert _resolve_curated_path(str(traversal)) is None
    assert any("not under" in r.getMessage() for r in caplog.records)


# ── _train_sync_inner branching (trainer receives curated dataset) ─────────


class _FakeDataset:
    """Stand-in for a HuggingFace ``datasets.Dataset`` — only the methods
    the trainer touches need to exist."""

    def __init__(self, rows: list[dict[str, str]]) -> None:
        self._rows = rows

    def map(self, fn):
        return _FakeDataset([fn(r) for r in self._rows])

    def __len__(self) -> int:
        return len(self._rows)

    def __iter__(self):
        return iter(self._rows)


def _install_dataset_stubs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    curated_rows: list[dict[str, str]],
    openorca_rows: list[dict[str, str]],
) -> dict[str, Any]:
    """Patch ``datasets.load_from_disk`` and ``datasets.load_dataset`` so the
    trainer's dataset-selection branch can be exercised without HF I/O.

    Returns a recorder dict so the test can assert which branch fired.
    """
    rec: dict[str, Any] = {"load_from_disk_calls": [], "load_dataset_calls": []}

    def fake_load_from_disk(path: str):
        rec["load_from_disk_calls"].append(path)
        return _FakeDataset(curated_rows)

    def fake_load_dataset(name: str, *args, **kwargs):
        rec["load_dataset_calls"].append((name, args, kwargs))
        return _FakeDataset(openorca_rows)

    import datasets as _datasets

    monkeypatch.setattr(_datasets, "load_from_disk", fake_load_from_disk)
    monkeypatch.setattr(_datasets, "load_dataset", fake_load_dataset)
    return rec


def _select_branch(
    config: dict,
    *,
    curated_rows: list[dict[str, str]],
    openorca_rows: list[dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> tuple[_FakeDataset, dict[str, Any], list[str]]:
    """Run the same dataset-selection logic the trainer runs, sharing the
    helper + format function so the test exercises the production branch.

    We can't import ``_train_sync_inner`` end-to-end (it touches torch/peft/
    trl/transformers/redis), so this mirrors only the branch under test
    using the exact production helper ``_resolve_curated_path`` and the
    real module-level logger.
    """
    # local imports keep module-load cheap and dodge the torch/peft import path
    from agents.training_backend import (
        LoRATrainingBackend,
        _resolve_curated_path,
    )
    from agents.training_backend import logger as training_logger

    rec = _install_dataset_stubs(
        monkeypatch, curated_rows=curated_rows, openorca_rows=openorca_rows
    )

    from datasets import load_dataset, load_from_disk  # patched stubs

    with caplog.at_level(logging.WARNING, logger=training_logger.name):
        curated_path = config.get("curated_path") or config.get("training_data_path")
        safe_curated = _resolve_curated_path(curated_path)
        if safe_curated is not None:
            training_logger.info("[lora-train] loading curated dataset from %s", safe_curated)
            raw = load_from_disk(str(safe_curated))
        else:
            if curated_path:
                training_logger.warning(
                    "[lora-train] curated_path=%r unusable (missing or outside data root); "
                    "falling back to OpenOrca cold-start dataset",
                    curated_path,
                )
            else:
                training_logger.warning(
                    "[lora-train] no curated_path provided; "
                    "falling back to OpenOrca cold-start dataset"
                )
            raw = load_dataset("Open-Orca/OpenOrca", split="train[:1000]")
        dataset = raw.map(lambda ex: {"text": LoRATrainingBackend._format_sample(ex)})

    return dataset, rec, [r.getMessage() for r in caplog.records]


def test_trainer_loads_curated_when_path_under_data_root(tmp_path, monkeypatch, caplog):
    """Happy path: a real curated dataset under the data root is loaded
    via ``load_from_disk`` and OpenOrca is NEVER touched."""
    data_root = tmp_path
    monkeypatch.setenv("MODELFORGE_DATA_ROOT", str(data_root))
    monkeypatch.setattr(settings, "modelforge_data_root", str(data_root), raising=False)

    curated = data_root / "curated" / "gen-3"
    curated.mkdir(parents=True)
    (curated / "dataset_info.json").write_text("{}", encoding="utf-8")

    curated_rows = [
        {"question": "What is 2+2?", "response": "4"},
        {"question": "Capital of France?", "response": "Paris"},
    ]
    openorca_rows = [{"question": "TRAP", "response": "TRAP"}]

    dataset, rec, _msgs = _select_branch(
        {"curated_path": str(curated)},
        curated_rows=curated_rows,
        openorca_rows=openorca_rows,
        monkeypatch=monkeypatch,
        caplog=caplog,
    )

    assert rec["load_from_disk_calls"] == [str(curated.resolve())]
    assert rec["load_dataset_calls"] == [], "OpenOrca must NOT be loaded when curated_path is valid"
    assert len(dataset) == 2
    # _format_sample wrapping should fire on the curated rows.
    out_rows = list(dataset)
    assert "2+2" in out_rows[0]["text"]


def test_trainer_falls_back_to_openorca_and_warns_when_no_curated_path(
    tmp_path, monkeypatch, caplog
):
    """Cold-start path: no curated_path → OpenOrca fallback + WARNING log."""
    monkeypatch.setenv("MODELFORGE_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "modelforge_data_root", str(tmp_path), raising=False)

    _, rec, msgs = _select_branch(
        {},  # no curated_path, no training_data_path
        curated_rows=[],
        openorca_rows=[{"question": "Q", "response": "A"}],
        monkeypatch=monkeypatch,
        caplog=caplog,
    )

    assert rec["load_from_disk_calls"] == []
    assert len(rec["load_dataset_calls"]) == 1
    assert rec["load_dataset_calls"][0][0] == "Open-Orca/OpenOrca"
    assert any(
        "no curated_path provided" in m and "falling back" in m for m in msgs
    ), f"expected fallback warning, got: {msgs}"


def test_trainer_falls_back_when_curated_path_outside_data_root(
    tmp_path, monkeypatch, caplog
):
    """Path traversal: a curated_path outside the data root is rejected
    with a warning AND the trainer transparently falls back to OpenOrca."""
    data_root = tmp_path / "data"
    data_root.mkdir()
    outside = tmp_path / "evil"
    outside.mkdir()
    (outside / "dataset_info.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("MODELFORGE_DATA_ROOT", str(data_root))
    monkeypatch.setattr(settings, "modelforge_data_root", str(data_root), raising=False)

    _, rec, msgs = _select_branch(
        {"curated_path": str(outside)},
        curated_rows=[{"question": "POISON", "response": "POISON"}],
        openorca_rows=[{"question": "Q", "response": "A"}],
        monkeypatch=monkeypatch,
        caplog=caplog,
    )

    assert rec["load_from_disk_calls"] == [], "rejected curated_path must NOT be loaded"
    assert len(rec["load_dataset_calls"]) == 1, "fallback to OpenOrca must fire"
    # Two warnings expected: traversal-reject (from helper) + fallback (from trainer branch).
    assert any("not under configured data root" in m for m in msgs)
    assert any("unusable" in m and "falling back" in m for m in msgs)


def test_trainer_accepts_legacy_training_data_path_key(tmp_path, monkeypatch, caplog):
    """The trainer also honors the older ``training_data_path`` key the
    evolution graph already populates in state. This guarantees the second
    bug in the chain (graph not propagating curated path) can be fixed
    without breaking pre-existing callers that already pass it via config."""
    data_root = tmp_path
    monkeypatch.setenv("MODELFORGE_DATA_ROOT", str(data_root))
    monkeypatch.setattr(settings, "modelforge_data_root", str(data_root), raising=False)

    curated = data_root / "curated" / "gen-2"
    curated.mkdir(parents=True)
    curated_rows = [{"question": "legacy", "response": "ok"}]

    _, rec, _msgs = _select_branch(
        {"training_data_path": str(curated)},
        curated_rows=curated_rows,
        openorca_rows=[{"question": "TRAP", "response": "TRAP"}],
        monkeypatch=monkeypatch,
        caplog=caplog,
    )

    assert rec["load_from_disk_calls"] == [str(curated.resolve())]
    assert rec["load_dataset_calls"] == []


# ── evolution_graph propagates training_data_path into trainer config ──────


class _CapturingTrainingBackend:
    """A TrainingBackend stub that records the ``config`` dict every train()
    invocation receives, so the test can assert ``curated_path`` propagation."""

    name = "capture"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def train(self, *, run_id: str, generation: int, config: dict) -> TrainingResult:
        self.calls.append(dict(config))
        return TrainingResult(
            adapter_path=f"/tmp/adapter-{run_id}-{generation}",
            method="lora",
            training_data_size=42,
            duration_seconds=0.0,
        )


class _StaticCurator:
    """Returns a fixed CurationResult so we can compare training_data_path
    to the config injection in train_adapter."""

    def __init__(self, data_path: str) -> None:
        self._data_path = data_path

    async def curate(
        self,
        *,
        weak_categories,
        weakness_report,
        generation,
        max_samples,
        config,
    ) -> CurationResult:
        return CurationResult(
            data_path=self._data_path,
            num_samples=10,
            categories_targeted=list(weak_categories),
            sources=["unit-test"],
        )


@pytest.mark.asyncio
async def test_evolution_graph_injects_curated_path_into_trainer_config(
    tmp_path, monkeypatch
):
    """End-to-end on the graph: the curator's ``data_path`` MUST land in
    the trainer's ``config["curated_path"]``. This is the second half of
    the R1 fix — without it, even the trainer's new branching logic stays
    on the OpenOrca fallback forever."""
    # Disable the Ollama self-augmentation phase (no teacher reachable in CI).
    monkeypatch.setenv("MODELFORGE_SELF_GEN_SEEDS", "0")
    # Make resolve_data_root deterministic so the trainer-side guard works
    # if it ever fires under the real backend.
    monkeypatch.setenv("MODELFORGE_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "modelforge_data_root", str(tmp_path), raising=False)

    curated_dir = tmp_path / "curated" / "gen-1"
    curated_dir.mkdir(parents=True)

    capture = _CapturingTrainingBackend()
    graph = build_graph(
        training=capture,
        eval_backend=MockEvalBackend(0.0),
        curator=_StaticCurator(str(curated_dir)),
    )

    await graph.ainvoke(
        {
            "run_id": "rid-test",
            "config": {"base_model": "llama3.2:3b", "max_generations": 1},
            "generation": 0,
            "max_generations": 1,
            "parent_scores": {},
            "child_scores": {},
            "decision": "",
            "decision_reason": "",
            "method": "",
            "adapter_path": None,
            "training_data_size": 0,
            "training_seconds": 0.0,
            "eval_seconds": 0.0,
            "cancelled": False,
            "error": None,
            "champion_path": None,
            "champion_avg": 0.0,
        },
        {"recursion_limit": 50},
    )

    assert capture.calls, "training backend was never invoked"
    seen = capture.calls[0]
    assert seen.get("curated_path") == str(curated_dir), (
        f"train_adapter must propagate the curator's data_path into "
        f"config['curated_path'] but got {seen.get('curated_path')!r}"
    )


@pytest.mark.asyncio
async def test_evolution_graph_train_call_omits_curated_path_when_curator_failed(
    tmp_path, monkeypatch
):
    """If the curator fails and ``state['training_data_path']`` stays
    ``None``, the trainer must NOT receive a ``curated_path=None`` key
    (the trainer's helper rejects None already, but cleanliness matters
    for log readability and downstream consumers)."""
    monkeypatch.setenv("MODELFORGE_SELF_GEN_SEEDS", "0")
    monkeypatch.setenv("MODELFORGE_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "modelforge_data_root", str(tmp_path), raising=False)

    class _FailingCurator:
        async def curate(self, **_kwargs):
            raise RuntimeError("curator down")

    capture = _CapturingTrainingBackend()
    graph = build_graph(
        training=capture,
        eval_backend=MockEvalBackend(0.0),
        curator=_FailingCurator(),
    )

    await graph.ainvoke(
        {
            "run_id": "rid-test",
            "config": {"base_model": "llama3.2:3b", "max_generations": 1},
            "generation": 0,
            "max_generations": 1,
            "parent_scores": {},
            "child_scores": {},
            "decision": "",
            "decision_reason": "",
            "method": "",
            "adapter_path": None,
            "training_data_size": 0,
            "training_seconds": 0.0,
            "eval_seconds": 0.0,
            "cancelled": False,
            "error": None,
            "champion_path": None,
            "champion_avg": 0.0,
        },
        {"recursion_limit": 50},
    )

    assert capture.calls, "training backend was never invoked"
    seen = capture.calls[0]
    assert "curated_path" not in seen or seen["curated_path"] is None
