"""CORS wildcard guard: when * is in CORS_ORIGINS, credentials must be off."""

from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def _client(monkeypatch, cors: str):
    monkeypatch.setenv("CORS_ORIGINS", cors)
    monkeypatch.setenv("MODELFORGE_API_KEY", "k")
    monkeypatch.setenv("ENVIRONMENT", "development")
    import config.settings as settings_module

    importlib.reload(settings_module)
    import app as app_module

    importlib.reload(app_module)
    return TestClient(app_module.create_app())


def test_wildcard_disables_credentials(monkeypatch):
    client = _client(monkeypatch, "http://localhost:3000,*")
    resp = client.options(
        "/api/system/status",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # When wildcard is on, Allow-Credentials must NOT be true (the spec
    # forbids the combination — Starlette therefore omits the header).
    assert resp.headers.get("access-control-allow-credentials") != "true"


def test_explicit_origin_allows_credentials(monkeypatch):
    client = _client(monkeypatch, "http://localhost:3000")
    resp = client.options(
        "/api/system/status",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers.get("access-control-allow-credentials") == "true"
