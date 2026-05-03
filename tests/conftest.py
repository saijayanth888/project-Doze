"""Pytest fixtures and path setup.

- Adds ``model-forge/src`` to ``sys.path`` so tests import the same way
  the running app does.
- Auto-chdirs every test into a tmp directory so the repo's local
  ``.env`` doesn't bleed into the values pydantic-settings loads.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    """Run every test in an empty cwd so ``Settings`` doesn't pick up the repo .env."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MODELFORGE_API_KEY", "test-key")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")
    yield


# Ensure environment baseline is set even before fixtures run, for any
# import-time evaluation that might happen during collection.
os.environ.setdefault("MODELFORGE_API_KEY", "test-key")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
