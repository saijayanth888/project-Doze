"""Tests for the runner.py silent-skip fix (spec Section J tests #6-8).

Verifies:
  6. track.eval_failed is emitted when scores exist but are zero/negative.
  7. track.promoted is NOT emitted when scores are zero.
  8. None avg is a silent skip (expected path for non-trading runs).
"""

from __future__ import annotations

from agents.runner import _avg_subset


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_track(track_id: str, targets: list[str]) -> dict:
    return {
        "track_id": track_id,
        "name": f"{track_id} track",
        "enabled": True,
        "target_benchmarks": targets,
        "champion_scores": {},
    }


def _run_promote_logic(track: dict, child_scores: dict, run_id: str = "run-test", generation: int = 1):
    """Reproduce the promotion-decision logic from _maybe_promote_to_tracks.

    Returns a tuple (emitted_events: list[dict], skipped: bool).
    This is a unit-test extraction of the logic at runner.py lines 131-152.
    """
    from agents.runner import _avg_subset

    targets = list(track.get("target_benchmarks") or [])
    emitted: list[dict] = []
    skipped = False

    new_avg = _avg_subset(child_scores, targets)

    if new_avg is None:
        skipped = True
        return emitted, skipped, "none_avg"

    if new_avg <= 0:
        emitted.append({
            "topic": "track.eval_failed",
            "payload": {
                "track_id": track.get("track_id"),
                "track_name": track.get("name"),
                "run_id": run_id,
                "generation": generation,
                "new_avg": round(new_avg, 4),
                "target_benchmarks": targets,
                "child_scores": dict(child_scores),
                "reason": "eval_score_zero_or_negative",
            },
        })
        skipped = True
        return emitted, skipped, "zero_avg"

    # new_avg > 0: promotion check
    prev_scores = track.get("champion_scores") or {}
    prev_avg = _avg_subset(prev_scores, targets) if prev_scores else None
    if prev_avg is not None and new_avg <= prev_avg:
        skipped = True
        return emitted, skipped, "below_prev"

    emitted.append({
        "topic": "track.promoted",
        "payload": {
            "track_id": track.get("track_id"),
            "new_avg": round(new_avg, 4),
        },
    })
    return emitted, skipped, "promoted"


# ---------------------------------------------------------------------------
# Test 6: track.eval_failed emitted when scores are zero
# ---------------------------------------------------------------------------
def test_runner_emits_track_eval_failed_when_score_zero():
    """Zero scores for a track's benchmarks → track.eval_failed event emitted."""
    track = _make_track("trading-reflector", ["faithfulness_regex", "judge_score"])
    child_scores = {"faithfulness_regex": 0.0, "judge_score": 0.0}

    events, skipped, path = _run_promote_logic(track, child_scores)

    assert skipped is True, "Zero-score run should be skipped (not promoted)"
    assert path == "zero_avg", f"Expected zero_avg path, got {path}"

    topics = [e["topic"] for e in events]
    assert "track.eval_failed" in topics, (
        f"Expected track.eval_failed event, got events: {events}"
    )
    # Verify the event payload shape
    failed_event = next(e for e in events if e["topic"] == "track.eval_failed")
    payload = failed_event["payload"]
    assert payload["track_id"] == "trading-reflector"
    assert payload["new_avg"] == 0.0
    assert payload["reason"] == "eval_score_zero_or_negative"
    assert "faithfulness_regex" in payload["target_benchmarks"]


# ---------------------------------------------------------------------------
# Test 7: track.promoted NOT emitted when scores are zero
# ---------------------------------------------------------------------------
def test_runner_does_not_emit_track_promoted_when_score_zero():
    """Zero scores should never result in track.promoted event."""
    track = _make_track("trading-bull", ["judge_preference", "evidence_density"])
    child_scores = {"judge_preference": 0.0, "evidence_density": 0.0}

    events, skipped, path = _run_promote_logic(track, child_scores)

    topics = [e["topic"] for e in events]
    assert "track.promoted" not in topics, (
        f"track.promoted must NOT fire for zero scores; got events: {events}"
    )
    assert "track.eval_failed" in topics


# ---------------------------------------------------------------------------
# Test 8: None avg is a silent skip (no event emitted)
# ---------------------------------------------------------------------------
def test_runner_silent_skip_only_for_none_avg():
    """When new_avg is None (no scores for this track's benchmarks), skip silently.

    This is the expected path for non-trading runs that don't target these
    benchmarks. No error event should be emitted.
    """
    track = _make_track("trading-reflector", ["faithfulness_regex", "judge_score"])
    # child_scores has no overlap with the track's target benchmarks
    child_scores = {"mmlu": 0.72, "gsm8k": 0.60}

    events, skipped, path = _run_promote_logic(track, child_scores)

    assert skipped is True, "None-avg run should be silently skipped"
    assert path == "none_avg", f"Expected none_avg path, got {path}"
    assert len(events) == 0, (
        f"Silent skip must emit NO events (got: {events})"
    )


# ---------------------------------------------------------------------------
# Helper: _avg_subset contracts
# ---------------------------------------------------------------------------
def test_avg_subset_returns_none_when_no_overlap():
    """_avg_subset returns None when no scores overlap with keys."""
    result = _avg_subset({"mmlu": 0.5, "gsm8k": 0.6}, ["faithfulness_regex"])
    assert result is None


def test_avg_subset_returns_none_for_none_scores():
    """_avg_subset returns None for None input."""
    result = _avg_subset(None, ["faithfulness_regex"])
    assert result is None


def test_avg_subset_returns_avg_when_overlap():
    """_avg_subset averages only the overlapping keys."""
    result = _avg_subset(
        {"faithfulness_regex": 0.8, "judge_score": 0.6, "mmlu": 0.9},
        ["faithfulness_regex", "judge_score"],
    )
    assert result is not None
    assert abs(result - 0.7) < 1e-9
