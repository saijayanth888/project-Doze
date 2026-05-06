"""Multi-objective Pareto-dominant selection.

Replaces the simple "average score went up → promote" heuristic that the
orchestrator used previously. Pareto dominance prevents the canonical failure
mode where a child gains 5% on MMLU but loses 10% on GSM8K and the average
still improves.

Decision rule
-------------
Promote iff EITHER:
  - the child is *strictly better* on every benchmark, OR
  - the child is *better on at least one* benchmark AND *not worse on any
    benchmark by more than ``threshold``* (default 1%).

Discard otherwise. The threshold defaults to 0.01 here (paper-grade strict
selection); the looser 0.03 used by ``regression_detector`` still applies as
a separate per-benchmark and held-out catastrophic-forgetting guard layered
on top in ``compare_to_champion``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("modelforge.pareto")


def _env_threshold(default: float) -> float:
    raw = os.environ.get("MODELFORGE_PARETO_THRESHOLD")
    if raw is None:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


@dataclass
class ParetoFinding:
    benchmark: str
    parent: float
    child: float
    delta: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark": self.benchmark,
            "parent": float(self.parent),
            "child": float(self.child),
            "delta": float(self.delta),
        }


@dataclass
class ParetoReport:
    promote: bool
    reason: str
    threshold: float
    strictly_better_on: list[str] = field(default_factory=list)
    worse_on: list[str] = field(default_factory=list)   # any negative delta
    blocking: list[str] = field(default_factory=list)   # delta < -threshold
    details: list[ParetoFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "promote": bool(self.promote),
            "reason": self.reason,
            "threshold": float(self.threshold),
            "strictly_better_on": list(self.strictly_better_on),
            "worse_on": list(self.worse_on),
            "blocking": list(self.blocking),
            "details": [d.to_dict() for d in self.details],
        }


def is_pareto_dominant(
    child_scores: dict[str, float] | None,
    parent_scores: dict[str, float] | None,
    *,
    threshold: float | None = None,
) -> ParetoReport:
    """Decide whether ``child`` Pareto-dominates ``parent`` within ``threshold``.

    Returns a structured report so callers can log + persist the decision rationale
    rather than just a boolean.
    """
    th = float(threshold if threshold is not None else _env_threshold(0.01))
    p = dict(parent_scores or {})
    c = dict(child_scores or {})

    # No parent → first generation is always a "promote" (no baseline to dominate).
    # Caller decides this; we just report no-op.
    if not p:
        return ParetoReport(
            promote=True,
            reason="No parent scores — first generation auto-promotes.",
            threshold=th,
        )
    if not c:
        return ParetoReport(
            promote=False,
            reason="Child has no scores — cannot compare.",
            threshold=th,
        )

    benches = [b for b in p.keys() if b in c and isinstance(c[b], (int, float)) and isinstance(p[b], (int, float))]
    if not benches:
        return ParetoReport(
            promote=False,
            reason="No overlapping benchmarks between parent and child.",
            threshold=th,
        )

    findings: list[ParetoFinding] = []
    strictly_better_on: list[str] = []
    worse_on: list[str] = []
    blocking: list[str] = []

    for b in benches:
        parent_v = float(p[b])
        child_v = float(c[b])
        delta = child_v - parent_v
        findings.append(ParetoFinding(benchmark=b, parent=parent_v, child=child_v, delta=delta))
        if delta > 0:
            strictly_better_on.append(b)
        if delta < 0:
            worse_on.append(b)
        if delta < -th:
            blocking.append(b)

    findings.sort(key=lambda f: f.delta)  # worst first

    detail_str = ", ".join(f"{f.benchmark} {f.delta:+.3f}" for f in findings)

    if blocking:
        return ParetoReport(
            promote=False,
            reason=f"Pareto block: regressed on {', '.join(blocking)} > -{th:.3f} ({detail_str})",
            threshold=th,
            strictly_better_on=strictly_better_on,
            worse_on=worse_on,
            blocking=blocking,
            details=findings,
        )

    if len(strictly_better_on) == len(benches):
        return ParetoReport(
            promote=True,
            reason=f"Strict dominance — better on all {len(benches)} benchmarks ({detail_str})",
            threshold=th,
            strictly_better_on=strictly_better_on,
            worse_on=worse_on,
            blocking=blocking,
            details=findings,
        )

    if strictly_better_on:
        return ParetoReport(
            promote=True,
            reason=f"Pareto improvement on {', '.join(strictly_better_on)} (no regression > -{th:.3f}; {detail_str})",
            threshold=th,
            strictly_better_on=strictly_better_on,
            worse_on=worse_on,
            blocking=blocking,
            details=findings,
        )

    return ParetoReport(
        promote=False,
        reason=f"No improvement on any benchmark ({detail_str})",
        threshold=th,
        strictly_better_on=strictly_better_on,
        worse_on=worse_on,
        blocking=blocking,
        details=findings,
    )
