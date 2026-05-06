"""Per-benchmark score regression detector.

A new generation that lifts the average by 2% but tanks code by 10% is a bad
trade — the orchestrator should discard it instead of promoting. This service
encapsulates that policy so it's testable in isolation and overridable from
the run config.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("modelforge.regression")


def _env_threshold(default: float) -> float:
    raw = os.environ.get("MODELFORGE_REGRESSION_THRESHOLD")
    if raw is None:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


@dataclass
class RegressionFinding:
    benchmark: str
    old_score: float
    new_score: float
    delta: float          # new - old; negative = regression

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark": self.benchmark,
            "old_score": float(self.old_score),
            "new_score": float(self.new_score),
            "delta": float(self.delta),
        }


@dataclass
class RegressionReport:
    regression_detected: bool
    threshold: float
    details: list[RegressionFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "regression_detected": bool(self.regression_detected),
            "threshold": float(self.threshold),
            "details": [d.to_dict() for d in self.details],
        }

    def summary(self) -> str:
        if not self.details:
            return "No per-benchmark regressions vs parent."
        worst = min(self.details, key=lambda d: d.delta)
        if not self.regression_detected:
            return (
                f"Soft regressions on {len(self.details)} bench(es); worst "
                f"{worst.benchmark} {worst.delta:+.4f} (within ±{self.threshold:.3f})."
            )
        return (
            f"Regression on {sum(1 for d in self.details if d.delta < -self.threshold)} bench(es); "
            f"worst {worst.benchmark} {worst.delta:+.4f} ≤ -{self.threshold:.3f}."
        )


def detect_regressions(
    parent_scores: dict[str, float] | None,
    child_scores: dict[str, float] | None,
    *,
    threshold: float | None = None,
) -> RegressionReport:
    """Compare parent vs child per-benchmark scores.

    `threshold` is the per-benchmark drop allowed before flagging (default 0.03,
    overridable via `MODELFORGE_REGRESSION_THRESHOLD` env or kwarg). When the
    parent score is missing for a benchmark, we never flag — first generations
    have no baseline.
    """
    th = float(threshold if threshold is not None else _env_threshold(0.03))
    p = dict(parent_scores or {})
    c = dict(child_scores or {})
    if not p or not c:
        return RegressionReport(regression_detected=False, threshold=th, details=[])

    findings: list[RegressionFinding] = []
    detected = False
    for bench, new_v in c.items():
        try:
            new_score = float(new_v)
        except (TypeError, ValueError):
            continue
        if bench not in p:
            continue
        try:
            old_score = float(p[bench])
        except (TypeError, ValueError):
            continue
        delta = new_score - old_score
        if delta < 0:
            findings.append(
                RegressionFinding(
                    benchmark=bench,
                    old_score=old_score,
                    new_score=new_score,
                    delta=delta,
                )
            )
            if delta < -th:
                detected = True

    findings.sort(key=lambda d: d.delta)  # worst first
    report = RegressionReport(
        regression_detected=detected,
        threshold=th,
        details=findings,
    )
    logger.info("[regression] %s", report.summary())
    return report
