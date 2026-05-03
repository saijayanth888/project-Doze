"""Settings load + validation guards."""

from __future__ import annotations

import importlib

import pytest


def _reload_settings(monkeypatch, **env: str):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import config.settings as settings_module

    importlib.reload(settings_module)
    return settings_module.Settings()


def test_loads_defaults(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    s = _reload_settings(monkeypatch, MODELFORGE_API_KEY="dev")
    assert s.environment == "development"
    assert s.is_production is False
    assert s.cors_origin_list


def test_production_requires_api_key(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("MODELFORGE_API_KEY", raising=False)
    import config.settings as settings_module

    importlib.reload(settings_module)
    # _env_file=None bypasses any stray .env so the missing key isn't
    # rescued by the repo's example file.
    s = settings_module.Settings(_env_file=None)
    with pytest.raises(RuntimeError, match="MODELFORGE_API_KEY"):
        s.validate_for_runtime()


def test_cors_wildcard_detected(monkeypatch):
    s = _reload_settings(
        monkeypatch,
        MODELFORGE_API_KEY="x",
        ENVIRONMENT="development",
        CORS_ORIGINS="http://localhost:3000,*",
    )
    assert s.cors_has_wildcard is True
    assert "*" in s.cors_origin_list
