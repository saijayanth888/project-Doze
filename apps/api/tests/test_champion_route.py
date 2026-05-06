"""GET /api/models/champion tolerates loose registry JSON (no 5xx from validation)."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_registry(monkeypatch, tmp_path):
    monkeypatch.setenv("MODELFORGE_API_KEY", "test-key")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("MODELFORGE_DATA_ROOT", str(root))

    import api.router as router_module
    import api.routes.models as models_routes
    import app as app_module
    import config.settings as settings_module
    import services.model_registry as model_registry_module

    importlib.reload(settings_module)
    importlib.reload(model_registry_module)
    importlib.reload(models_routes)
    importlib.reload(router_module)
    importlib.reload(app_module)
    return TestClient(app_module.create_app()), root


def test_champion_404_when_empty(client_with_registry):
    client, root = client_with_registry
    reg = {"champion": None, "models": []}
    (root / "registry.json").write_text(json.dumps(reg), encoding="utf-8")
    r = client.get("/api/models/champion", headers={"X-API-Key": "test-key"})
    assert r.status_code == 404


def test_champion_200_normalizes_loose_types(client_with_registry):
    client, root = client_with_registry
    reg = {
        "champion": {
            "generation": "2",
            "base_model": "llama3.2:3b",
            "scores": {"mmlu": "0.41", "arc_challenge": 0.5},
            "avg_score": "0.455",
        },
        "models": [],
    }
    (root / "registry.json").write_text(json.dumps(reg), encoding="utf-8")
    r = client.get("/api/models/champion", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    body = r.json()
    assert body["generation"] == 2
    assert body["base_model"] == "llama3.2:3b"
    assert body["scores"]["mmlu"] == 0.41
    assert body["scores"]["arc_challenge"] == 0.5


def test_champion_404_when_base_model_missing(client_with_registry):
    client, root = client_with_registry
    reg = {
        "champion": {"generation": 1, "scores": {}, "avg_score": 0},
        "models": [],
    }
    (root / "registry.json").write_text(json.dumps(reg), encoding="utf-8")
    r = client.get("/api/models/champion", headers={"X-API-Key": "test-key"})
    assert r.status_code == 404
