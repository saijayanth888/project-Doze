"""APIKeyMiddleware allowlist + 401 behaviour."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("MODELFORGE_API_KEY", "expected-key")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")

    import config.settings as settings_module

    importlib.reload(settings_module)
    import app as app_module

    importlib.reload(app_module)

    return TestClient(app_module.create_app())


def test_status_is_open(client):
    assert client.get("/api/system/status").status_code == 200


def test_models_requires_key(client):
    assert client.get("/api/models/").status_code == 401


def test_wrong_key_rejected(client):
    resp = client.get("/api/models/", headers={"X-API-Key": "nope"})
    assert resp.status_code == 401
    assert resp.json()["status"] == "error"


def test_correct_key_passes(client):
    resp = client.get("/api/models/", headers={"X-API-Key": "expected-key"})
    assert resp.status_code == 200


def test_security_headers_present(client):
    resp = client.get("/api/system/status")
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
