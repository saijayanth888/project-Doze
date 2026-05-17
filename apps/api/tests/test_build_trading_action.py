"""Tests for the BuildTradingDataset action (dataset.build_trading).

Four tests per spec Section J / Commit 7:
  1. test_reject_invalid_track_id — bad track_id → status="error"
  2. test_reject_when_db_unreachable — _probe_db returns False → status="error"
  3. test_success_returns_records_count_from_curator_result — mock subprocess
     + write real curator_result.json → status="ok", records_count matches
  4. test_failure_when_curator_result_missing — subprocess exits 0 but no
     curator_result.json file → status="error"
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch


import pytest


def _run(coro):
    """Tiny helper — run an async coroutine in tests that don't use pytest-asyncio."""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def action():
    """Return a fresh BuildTradingDataset instance."""
    from agents.actions.dataset_build_trading import BuildTradingDataset
    return BuildTradingDataset()


@pytest.fixture()
def minimal_context():
    return {}


@pytest.fixture()
def minimal_engine():
    return MagicMock()


# ---------------------------------------------------------------------------
# Test 1: invalid track_id is rejected immediately (before any I/O or DB probe)
# ---------------------------------------------------------------------------

def test_reject_invalid_track_id(action, minimal_context, minimal_engine):
    config = {"track_id": "trading-bogus", "ingest_date": "yesterday"}
    result = _run(action.execute(config=config, context=minimal_context, engine=minimal_engine))
    assert result.status == "error", f"Expected error, got {result.status!r}"
    assert result.error == "invalid_track_id"
    assert "trading-bogus" in (result.message or "")


def test_reject_all_empty_track_id(action, minimal_context, minimal_engine):
    """Blank track_id is also invalid."""
    config = {"track_id": "", "ingest_date": "yesterday"}
    result = _run(action.execute(config=config, context=minimal_context, engine=minimal_engine))
    assert result.status == "error"
    assert result.error == "invalid_track_id"


# ---------------------------------------------------------------------------
# Test 2: DB probe failure returns tradebot_db_unreachable
# ---------------------------------------------------------------------------

def test_reject_when_db_unreachable(action, minimal_context, minimal_engine, monkeypatch):
    """When _probe_db returns False, the action must return status="error"."""
    monkeypatch.setenv("TRADEBOT_DATABASE_URL", "postgresql://fake:fake@nowhere:5434/postgres")

    import agents.actions.dataset_build_trading as _mod
    with patch.object(_mod, "_probe_db", return_value=False):
        config = {"track_id": "trading-arbiter", "ingest_date": "yesterday"}
        result = _run(action.execute(config=config, context=minimal_context, engine=minimal_engine))

    assert result.status == "error", f"Expected error, got {result.status!r}"
    assert result.error == "tradebot_db_unreachable"
    assert (result.output or {}).get("track_id") == "trading-arbiter"


# ---------------------------------------------------------------------------
# Test 3: Success path — mocked subprocess + real curator_result.json
# ---------------------------------------------------------------------------

def test_success_returns_records_count_from_curator_result(
    action, minimal_context, minimal_engine, tmp_path, monkeypatch,
):
    """Mock subprocess returns rc=0; write a valid curator_result.json; assert ok."""
    track_id = "trading-regime-tagger"
    dgx_root = tmp_path / "dgx-train"

    # Write the curator_result.json that BuildTradingDataset will read.
    result_dir = dgx_root / "datasets" / track_id
    result_dir.mkdir(parents=True)
    test_set_path = str(result_dir / "test_set.jsonl")
    curated_path = str(result_dir / "curated")
    curator_result = {
        "status": "ok",
        "track_id": track_id,
        "accept_count": 47,
        "reject_count": 3,
        "test_set_count": 8,
        "reject_reasons": {},
        "out_path": curated_path,
        "test_set_path": test_set_path,
        "timestamp_utc": "2026-05-18T04:31:00+00:00",
    }
    (result_dir / "curator_result.json").write_text(json.dumps(curator_result))

    # No DB probe needed — TRADEBOT_DATABASE_URL not set → skips probe.
    monkeypatch.delenv("TRADEBOT_DATABASE_URL", raising=False)

    import subprocess
    fake_completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="ok", stderr="",
    )

    with patch("subprocess.run", return_value=fake_completed):
        config = {
            "track_id": track_id,
            "ingest_date": "yesterday",
            "dgx_train_root": str(dgx_root),
        }
        result = _run(action.execute(config=config, context=minimal_context, engine=minimal_engine))

    assert result.status == "ok", f"Expected ok, got {result.status!r}: {result.message}"
    assert (result.output or {}).get("records_count") == 47
    assert (result.output or {}).get("test_set_count") == 8
    assert (result.output or {}).get("track_id") == track_id
    assert (result.output or {}).get("test_set_path") == test_set_path


# ---------------------------------------------------------------------------
# Test 4: curator_result.json missing after subprocess exits 0
# ---------------------------------------------------------------------------

def test_failure_when_curator_result_missing(
    action, minimal_context, minimal_engine, tmp_path, monkeypatch,
):
    """Subprocess exits 0 but curator_result.json is never written → error."""
    track_id = "trading-bull"
    dgx_root = tmp_path / "dgx-train"
    dgx_root.mkdir(parents=True)

    # Don't write curator_result.json — that's the failure condition.
    monkeypatch.delenv("TRADEBOT_DATABASE_URL", raising=False)

    import subprocess
    fake_completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="ok", stderr="",
    )

    with patch("subprocess.run", return_value=fake_completed):
        config = {
            "track_id": track_id,
            "ingest_date": "yesterday",
            "dgx_train_root": str(dgx_root),
        }
        result = _run(action.execute(config=config, context=minimal_context, engine=minimal_engine))

    assert result.status == "error", f"Expected error, got {result.status!r}"
    assert result.error == "curator_result_missing"
    assert "curator_result.json" in (result.message or "")


# ---------------------------------------------------------------------------
# Test 5: insufficient_data curator status surfaces as error
# ---------------------------------------------------------------------------

def test_insufficient_data_curator_status(
    action, minimal_context, minimal_engine, tmp_path, monkeypatch,
):
    """When curator_result.json says insufficient_data, action returns error."""
    track_id = "trading-bear"
    dgx_root = tmp_path / "dgx-train"
    result_dir = dgx_root / "datasets" / track_id
    result_dir.mkdir(parents=True)
    curator_result = {
        "status": "insufficient_data",
        "track_id": track_id,
        "accept_count": 12,
        "reject_count": 88,
        "test_set_count": 0,
        "reject_reasons": {"below_min_records_gate": 12, "crypto_term_contamination": 76},
        "out_path": None,
        "test_set_path": None,
        "timestamp_utc": "2026-05-18T04:31:00+00:00",
    }
    (result_dir / "curator_result.json").write_text(json.dumps(curator_result))
    monkeypatch.delenv("TRADEBOT_DATABASE_URL", raising=False)

    import subprocess
    fake_completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="ok", stderr="",
    )

    with patch("subprocess.run", return_value=fake_completed):
        config = {
            "track_id": track_id,
            "ingest_date": "yesterday",
            "dgx_train_root": str(dgx_root),
        }
        result = _run(action.execute(config=config, context=minimal_context, engine=minimal_engine))

    assert result.status == "error"
    assert result.error == "curator_result_insufficient_data"
    assert (result.output or {}).get("accept_count") == 12
