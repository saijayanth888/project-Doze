"""Verify the memory estimate is computed during /api/evolve/start.

Uses fastapi.testclient + monkeypatched start_evolution to avoid
actually scheduling a real training run during the test.
"""
from __future__ import annotations

import importlib
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MODELFORGE_API_KEY", "test-key")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")

    import config.settings as settings_module
    import app as app_module

    importlib.reload(settings_module)
    importlib.reload(app_module)

    from fastapi.testclient import TestClient
    return TestClient(app_module.create_app())


def _hdrs() -> dict[str, str]:
    return {"X-API-Key": os.environ.get("MODELFORGE_API_KEY", "test-key")}


def test_start_records_memory_estimate(client, monkeypatch):
    captured: dict = {}

    def fake_start(*, run_id, config, db):
        captured["config"] = config
        return None

    # Mock the DB dependency so we don't need a real database connection.
    mock_db = MagicMock()
    mock_db.save_run = AsyncMock(return_value=None)

    async def fake_get_db(request=None):
        return mock_db

    with patch("api.routes.evolution.start_evolution", side_effect=fake_start), \
         patch("api.deps.get_db", side_effect=fake_get_db):
        resp = client.post(
            "/api/evolve/start",
            headers=_hdrs(),
            json={
                "base_model": "meta-llama/Llama-3.2-3B-Instruct",
                "max_generations": 1,
                "max_samples": 200,
                "lora_rank": 8,
                "batch_size": 1,
            },
        )

    assert resp.status_code in (200, 202), resp.text
    assert "memory_estimate" in captured["config"]
    est = captured["config"]["memory_estimate"]
    assert "estimated_peak_gb" in est
    assert est["fits_128gb"] is True
