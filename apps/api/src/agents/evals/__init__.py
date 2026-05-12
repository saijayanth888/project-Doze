"""Trading-specific evaluation modules.

This package implements scoring backends for trading-bot's six LLM roles
(reflector, bull, bear, arbiter, regime-tagger, indicator-selector). Each
module exposes a single scoring callable that produces trading-meaningful
score keys (faithfulness, predictive_hit_rate_30d, downstream_pnl_per_decision,
etc.). The ``EVAL_REGISTRY`` in :mod:`eval_registry` dispatches by ``track_id``.

Standalone -- does not import anything from the trading-bot repo at runtime.
The Pydantic schemas used by structured-output evaluations are duplicated in
:mod:`trading_schemas` (see ``TRADING_EVALS_HANDOFF.md`` for the cross-repo
sync caveat).
"""

from __future__ import annotations

from agents.evals import (
    eval_arbiter,
    eval_debater,
    eval_reflector,
    eval_structured_json,
)
from agents.evals.eval_registry import EVAL_REGISTRY, resolve_eval

__all__ = [
    "EVAL_REGISTRY",
    "eval_arbiter",
    "eval_debater",
    "eval_reflector",
    "eval_structured_json",
    "resolve_eval",
]
