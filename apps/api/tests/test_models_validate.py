"""POST /api/models/validate — return HF metadata + LoRA targets + memory estimate."""
from __future__ import annotations

import os
from unittest.mock import patch

from fastapi.testclient import TestClient


def _hdrs():
    return {"X-API-Key": os.environ.get("MODELFORGE_API_KEY", "")}


def _client():
    from app import create_app
    return TestClient(create_app())


def test_validate_known_model_returns_lora_and_memory():
    fake_info = {
        "tags": ["llama", "instruct"],
        "private": False,
        "gated": False,
        "siblings": [],
    }
    with patch("api.routes.models._fetch_hf_model_info", return_value=fake_info):
        resp = _client().post(
            "/api/models/validate",
            headers=_hdrs(),
            json={"model_id": "meta-llama/Llama-3.2-3B-Instruct"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valid"] is True
    assert body["model_id"] == "meta-llama/Llama-3.2-3B-Instruct"
    assert body["gated"] is False
    assert "gate_proj" in body["lora_target_modules"]
    assert body["estimated_memory_gb"] > 0
    assert body["fits_128gb"] is True


def test_validate_unknown_model_returns_invalid():
    with patch("api.routes.models._fetch_hf_model_info", return_value=None):
        resp = _client().post(
            "/api/models/validate",
            headers=_hdrs(),
            json={"model_id": "nonexistent/model-9999"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert body["reason"] == "not_found"


def test_validate_rejects_missing_model_id():
    resp = _client().post("/api/models/validate", headers=_hdrs(), json={})
    assert resp.status_code == 422
