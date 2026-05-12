"""Track-id -> scoring-callable dispatch.

Used by :class:`agents.eval_backend.TradingEvalBackend` to pick the right
scoring module per track. Each entry returns an
:class:`agents.eval_backend.EvalResult` with the keys documented in the
corresponding module docstring.

The uniform signature is::

    scorer(adapter_path: str, test_set_path: str) -> EvalResult

Per-role variants (bull/bear role, schema selection) are wrapped via
``functools.partial`` so the registry hides those details.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from agents.eval_backend import EvalResult
from agents.evals import (
    eval_arbiter,
    eval_debater,
    eval_reflector,
    eval_structured_json,
)
from agents.evals.trading_schemas import IndicatorSelection, RegimeTag

# Wrap the role-parameterised modules so each registry entry has the same
# (adapter_path, test_set_path, **kwargs) shape callers expect.
_bull_scorer = functools.partial(eval_debater.score, role="bull")
_bear_scorer = functools.partial(eval_debater.score, role="bear")
_regime_scorer = functools.partial(eval_structured_json.score, schema=RegimeTag)
_indicator_scorer = functools.partial(eval_structured_json.score, schema=IndicatorSelection)


# Public dispatch table. Keys match trading-bot's track_ids (see
# trading-bot/docs/MODELFORGE_INTEGRATION_PLAN.md section 2).
EVAL_REGISTRY: dict[str, Callable[..., EvalResult]] = {
    "trading-reflector": eval_reflector.score,
    "trading-bull": _bull_scorer,
    "trading-bear": _bear_scorer,
    "trading-arbiter": eval_arbiter.score,
    "trading-regime-tagger": _regime_scorer,
    "trading-indicator-selector": _indicator_scorer,
}


def resolve_eval(track_id: str | None) -> Callable[..., EvalResult] | None:
    """Return the scoring callable for ``track_id``, or ``None`` if unknown.

    Returning ``None`` (rather than raising) lets the eval backend fall through
    to the canonical lm-eval-harness sweep for non-trading tracks. This is the
    additive-only invariant: legacy MMLU/GSM8K runs are untouched.
    """
    if not track_id:
        return None
    return EVAL_REGISTRY.get(track_id)


def list_track_ids() -> list[str]:
    """Sorted list of registered trading track_ids -- handy for the CLI."""
    return sorted(EVAL_REGISTRY.keys())


def run_for_track(
    track_id: str,
    adapter_path: str,
    test_set_path: str,
    **kwargs: Any,
) -> EvalResult:
    """Convenience wrapper: dispatch + invoke in one call.

    Raises ``KeyError`` if ``track_id`` is not registered. Use
    :func:`resolve_eval` if you want a None-fallthrough instead.
    """
    scorer = EVAL_REGISTRY.get(track_id)
    if scorer is None:
        raise KeyError(f"no trading eval registered for track_id={track_id!r}")
    return scorer(adapter_path, test_set_path, **kwargs)


__all__ = [
    "EVAL_REGISTRY",
    "list_track_ids",
    "resolve_eval",
    "run_for_track",
]
