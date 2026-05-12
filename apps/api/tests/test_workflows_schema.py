"""Schema validation tests for /api/automation/workflows POST/PUT.

The workflow_runner is tolerant of unknown action kinds at execution
time — it logs a step trace with status=error and continues. But that
means a typo in the dashboard form silently produces a workflow that
fails every time it fires, leaving a red row in the run history that
the operator has to debug.

The route layer should reject obviously-bad shapes up front so the
dashboard form can show a useful error inline.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


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
    return {"X-API-Key": "test-key"}


def _base_payload():
    return {
        "name": "test-workflow",
        "trigger_type": "manual",
        "trigger_config": {},
        "actions": [],
    }


def test_create_rejects_unknown_action_kind(client):
    payload = _base_payload()
    payload["actions"] = [{"kind": "definitely.not.a.real.kind", "config": {}}]
    resp = client.post("/api/automation/workflows", json=payload, headers=_hdrs())
    assert resp.status_code == 400, resp.text
    assert "not registered" in resp.text.lower()


def test_create_rejects_actions_not_a_list(client):
    payload = _base_payload()
    payload["actions"] = {"kind": "notify.slack"}  # dict instead of list
    resp = client.post("/api/automation/workflows", json=payload, headers=_hdrs())
    assert resp.status_code == 400, resp.text


def test_create_rejects_action_step_not_a_dict(client):
    payload = _base_payload()
    payload["actions"] = ["notify.slack"]  # string instead of object
    resp = client.post("/api/automation/workflows", json=payload, headers=_hdrs())
    assert resp.status_code == 400, resp.text


def test_create_rejects_action_missing_kind(client):
    payload = _base_payload()
    payload["actions"] = [{"config": {"message": "hi"}}]
    resp = client.post("/api/automation/workflows", json=payload, headers=_hdrs())
    assert resp.status_code == 400, resp.text


def test_create_rejects_action_config_not_an_object(client):
    payload = _base_payload()
    payload["actions"] = [{"kind": "notify.slack", "config": "this should be an object"}]
    resp = client.post("/api/automation/workflows", json=payload, headers=_hdrs())
    assert resp.status_code == 400, resp.text


def test_create_rejects_unknown_trigger_type(client):
    payload = _base_payload()
    payload["trigger_type"] = "interval"
    resp = client.post("/api/automation/workflows", json=payload, headers=_hdrs())
    assert resp.status_code == 400, resp.text


def test_create_rejects_missing_name(client):
    payload = _base_payload()
    payload["name"] = ""
    resp = client.post("/api/automation/workflows", json=payload, headers=_hdrs())
    assert resp.status_code == 400, resp.text
