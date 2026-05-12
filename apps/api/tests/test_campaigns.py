"""Tests for the /api/campaigns route.

The app + settings are reloaded inside the fixture so the API key seen by
the auth middleware matches the one the test sends. Without the reload,
when this module imports ``app`` at collection time, ``Settings()`` is
instantiated against whatever ``MODELFORGE_API_KEY`` happened to be set
first; later tests that monkeypatch a different value (e.g. test_app_cors
reloads with ``MODELFORGE_API_KEY=k``) leave the singleton holding the
wrong value and the campaigns request returns 401 instead of 200/404.
"""
from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient

from services.campaign_configs import CAMPAIGNS


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("MODELFORGE_API_KEY", "test-key")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")

    import config.settings as settings_module
    importlib.reload(settings_module)
    import app as app_module
    importlib.reload(app_module)

    return TestClient(app_module.create_app())


def _hdrs():
    return {"X-API-Key": os.environ.get("MODELFORGE_API_KEY", "")}


def test_list_campaigns_returns_all_known(client):
    resp = client.get("/api/campaigns", headers=_hdrs())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {c["id"] for c in body["campaigns"]}
    assert ids == set(CAMPAIGNS.keys())


def test_get_campaign_returns_404_for_unknown(client):
    resp = client.get("/api/campaigns/does-not-exist", headers=_hdrs())
    assert resp.status_code == 404


def test_each_campaign_has_description_and_experiments():
    for cid, cfg in CAMPAIGNS.items():
        assert cfg.get("description"), f"missing description for {cid}"
        assert isinstance(cfg.get("experiments"), list)
        assert len(cfg["experiments"]) > 0, f"no experiments for {cid}"
