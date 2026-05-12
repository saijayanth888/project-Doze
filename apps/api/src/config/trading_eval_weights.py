"""Trading-eval Pareto tiebreaker config.

Per trading-bot's locked decision **#3: predictive hit-rate wins**, certain
metrics carry veto power for a given track. When the priority metric regresses
by more than ``ROLLBACK_THRESHOLD_PCT`` relative to the parent, the candidate
is *flagged for rollback* regardless of how other scores moved.

This is layered on top of :mod:`services.pareto_selector` -- Pareto still has
to pass for promotion; this config just adds an extra veto when the trading-
specific signal is missing.

The mechanic is intentionally minimal: a single mapping consulted from
:mod:`agents.evolution_graph.compare_to_champion` when ``config["track_id"]``
starts with ``trading-``. Standard MMLU/GSM8K runs are untouched.
"""

from __future__ import annotations

from typing import Any

# Per-track priority metric. When this metric regresses more than the rollback
# threshold (default 5%) vs the parent, the candidate is discarded -- even if
# average benchmark scores improve.
PARETO_TIEBREAKER_PRIORITY: dict[str, str] = {
    "trading-reflector": "predictive_hit_rate_30d",
    "trading-bull": "judge_preference",
    "trading-bear": "judge_preference",
    "trading-arbiter": "downstream_pnl_per_decision",
    "trading-regime-tagger": "agreement_with_baseline",
    "trading-indicator-selector": "agreement_with_baseline",
}

# Default rollback threshold as a fraction. 0.05 == "metric must not drop by
# more than 5% of the parent's value". Override per-track via
# PARETO_ROLLBACK_THRESHOLDS below or via MODELFORGE_TRADING_ROLLBACK_THRESHOLD
# (an absolute fraction, e.g. ``0.05``).
DEFAULT_ROLLBACK_THRESHOLD_PCT: float = 0.05

# Per-track threshold overrides. Empty by default; populate only when a track
# needs a tighter or looser veto. Operator's locked-decision posture is "be
# strict on the arbiter, lenient on the debaters".
PARETO_ROLLBACK_THRESHOLDS: dict[str, float] = {
    "trading-arbiter": 0.03,
}


def get_tiebreaker_metric(track_id: str | None) -> str | None:
    """Return the priority metric for ``track_id``, or ``None`` if untracked."""
    if not track_id:
        return None
    return PARETO_TIEBREAKER_PRIORITY.get(track_id)


def get_rollback_threshold(track_id: str | None) -> float:
    """Per-track or default rollback threshold (fraction, e.g. 0.05)."""
    if track_id and track_id in PARETO_ROLLBACK_THRESHOLDS:
        return PARETO_ROLLBACK_THRESHOLDS[track_id]
    return DEFAULT_ROLLBACK_THRESHOLD_PCT


def check_tiebreaker(
    track_id: str | None,
    parent_scores: dict[str, float] | None,
    child_scores: dict[str, float] | None,
) -> dict[str, Any]:
    """Run the tiebreaker check.

    Returns a dict ``{"rollback": bool, "reason": str, "metric": str|None,
    "parent": float|None, "child": float|None, "delta_pct": float|None,
    "threshold_pct": float}``.

    ``rollback=True`` means the candidate failed the trading-specific veto and
    must be discarded by the caller. ``rollback=False`` does NOT mean
    "promote" -- it just means "the tiebreaker doesn't object; consult Pareto
    + regression guards as usual".
    """
    metric = get_tiebreaker_metric(track_id)
    threshold = get_rollback_threshold(track_id)

    result: dict[str, Any] = {
        "rollback": False,
        "reason": "",
        "metric": metric,
        "parent": None,
        "child": None,
        "delta_pct": None,
        "threshold_pct": threshold,
    }

    if metric is None:
        result["reason"] = "no trading tiebreaker registered for this track"
        return result

    parent_v = (parent_scores or {}).get(metric)
    child_v = (child_scores or {}).get(metric)

    if not isinstance(parent_v, (int, float)) or not isinstance(child_v, (int, float)):
        # No parent on this metric -> no veto (first generation, or metric
        # added mid-stream). Pareto/regression layers still apply.
        result["reason"] = (
            f"tiebreaker metric {metric!r} missing from parent or child -- veto skipped"
        )
        return result

    result["parent"] = float(parent_v)
    result["child"] = float(child_v)

    # Compute relative delta. When parent is ~0, use absolute delta against
    # the threshold so a metric stuck at 0 doesn't divide-by-zero.
    if abs(float(parent_v)) < 1e-9:
        # Parent ~ 0: any drop is at most threshold-sized in absolute terms.
        delta_abs = float(child_v) - float(parent_v)
        result["delta_pct"] = delta_abs
        if delta_abs < -threshold:
            result["rollback"] = True
            result["reason"] = (
                f"tiebreaker veto: {metric} dropped from {parent_v:.4f} to "
                f"{child_v:.4f} (delta {delta_abs:+.4f}, threshold {threshold:.2%})"
            )
        else:
            result["reason"] = f"tiebreaker pass: {metric} delta {delta_abs:+.4f}"
        return result

    delta_pct = (float(child_v) - float(parent_v)) / abs(float(parent_v))
    result["delta_pct"] = delta_pct
    if delta_pct < -threshold:
        result["rollback"] = True
        result["reason"] = (
            f"tiebreaker veto: {metric} regressed {delta_pct:+.2%} "
            f"(parent={parent_v:.4f}, child={child_v:.4f}, "
            f"threshold=-{threshold:.2%})"
        )
    else:
        result["reason"] = (
            f"tiebreaker pass: {metric} delta {delta_pct:+.2%} within tolerance"
        )
    return result


__all__ = [
    "DEFAULT_ROLLBACK_THRESHOLD_PCT",
    "PARETO_ROLLBACK_THRESHOLDS",
    "PARETO_TIEBREAKER_PRIORITY",
    "check_tiebreaker",
    "get_rollback_threshold",
    "get_tiebreaker_metric",
]
