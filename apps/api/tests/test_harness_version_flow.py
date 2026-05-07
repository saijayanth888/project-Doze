"""Smoke that harness_version flows through eval_backend → experiment_tracker."""
from __future__ import annotations

import pytest

from services.experiment_tracker import build_records


def test_experiment_record_includes_harness_version(monkeypatch):
    # Simulate a run + one generation row coming back from the DB.
    fake_runs = [{"run_id": "test-run", "base_model": "test/model", "config": {}, "started_at": None, "completed_at": None}]
    fake_gens = [{
        "generation": 0,
        "promoted": True,
        "child_scores": {"mmlu": 0.5},
        "parent_scores": {},
        "data": {"harness_version": "0.4.4-test"},
        "duration_seconds": 1.0,
    }]

    class FakeDB:
        async def list_runs(self, *, include_archived=False, limit=500):
            return fake_runs
        async def get_all_generations(self, *, run_id):
            return fake_gens

    import asyncio
    records = asyncio.run(build_records(FakeDB()))
    assert len(records) >= 1
    assert records[0]["system_metrics"]["harness_version"] == "0.4.4-test"
