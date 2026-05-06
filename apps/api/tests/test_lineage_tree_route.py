"""GET /api/lineage/tree falls back to registry champion when Postgres has no rows."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_registry_only(monkeypatch, tmp_path):
    monkeypatch.setenv("MODELFORGE_API_KEY", "test-key")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("MODELFORGE_DATA_ROOT", str(root))

    from services.lineage_db import LineageDB

    async def _no_generations(self, *args, **kwargs):
        """Force empty Postgres lineage so tests use registry fallback."""
        return []

    monkeypatch.setattr(LineageDB, "get_all_generations", _no_generations)

    import api.router as router_module
    import api.routes.lineage as lineage_routes
    import app as app_module
    import config.settings as settings_module
    import services.model_registry as model_registry_module

    importlib.reload(settings_module)
    importlib.reload(model_registry_module)
    importlib.reload(lineage_routes)
    importlib.reload(router_module)
    importlib.reload(app_module)
    return TestClient(app_module.create_app()), root


def test_lineage_tree_registry_fallback_when_db_empty(client_registry_only):
    client, root = client_registry_only
    reg = {
        "champion": {
            "generation": 1,
            "base_model": "meta-llama/Llama-3.2-3B-Instruct",
            "adapter_id": "run-abc12345-gen-1",
            "adapter_path": "/app/data/adapters/run-abc12345/gen-1",
            "scores": {"mmlu": 0.53, "gsm8k": 0.41},
            "avg_score": 0.47,
            "method": "lora",
        },
        "models": [],
    }
    (root / "registry.json").write_text(json.dumps(reg), encoding="utf-8")

    r = client.get("/api/lineage/tree", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    body = r.json()
    assert body["total_nodes"] == 1
    assert body["champion_id"] == "run-abc12345-gen-1"
    assert len(body["nodes"]) == 1
    n0 = body["nodes"][0]
    assert n0["generation"] == 1
    assert n0["is_champion"] is True
    assert n0["scores"]["mmlu"] == 0.53


def test_lineage_tree_registry_fallback_ollama_model_only(client_registry_only):
    """Champion row may omit base_model/name but include ollama_model (still listable in lineage)."""
    client, root = client_registry_only
    reg = {
        "champion": {
            "generation": 1,
            "adapter_id": "run-w7abcd01-gen-1",
            "ollama_model": "llama3.2:3b",
            "scores": {"mmlu": 0.5},
            "avg_score": 0.5,
        },
        "models": [],
    }
    (root / "registry.json").write_text(json.dumps(reg), encoding="utf-8")

    r = client.get("/api/lineage/tree", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    body = r.json()
    assert body["total_nodes"] == 1
    assert body["champion_id"] == "run-w7abcd01-gen-1"


def test_lineage_tree_empty_without_champion(client_registry_only):
    client, root = client_registry_only
    reg = {"champion": None, "models": []}
    (root / "registry.json").write_text(json.dumps(reg), encoding="utf-8")

    r = client.get("/api/lineage/tree", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    body = r.json()
    assert body["total_nodes"] == 0
    assert body["nodes"] == []
