"""Tiny JSON-expression evaluator for workflow conditions.

We deliberately don't pull in `python-json-logic` or write a parser — workflow
conditions only need ~10 operators and we want a 0-dependency surface that's
trivial to audit.

Expression form
---------------
::

    {"<": [{"var": "scores.gsm8k"}, 0.5]}
    {"and": [{"==": [{"var": "decision"}, "promote"]},
             {">": [{"var": "champion_avg"}, 0.6]}]}

Literals are passed as-is (numbers, strings, bools, lists). ``{"var": "a.b.c"}``
walks the context dict via dot-notation. Missing keys evaluate to ``None``.

A condition of ``None`` or ``{}`` always evaluates to ``True`` — this is the
"unconditional" path.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("modelforge.automation.conditions")


def _resolve_var(args: Any, ctx: dict[str, Any]) -> Any:
    """``{"var": "a.b.c"}`` walks ``ctx`` via dotted-key access."""
    path = args if isinstance(args, str) else (args[0] if isinstance(args, list) and args else "")
    if not path:
        return None
    cur: Any = ctx
    for part in str(path).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def evaluate(condition: Any, context: dict[str, Any] | None = None) -> bool | Any:
    """Evaluate ``condition`` against ``context``. Returns the operator's result.

    Most operators return ``bool``; ``var`` returns the resolved value (used by
    nested expressions). The final return value at the top of a condition is
    coerced to ``bool``.
    """
    ctx = context or {}
    if condition is None or condition == {}:
        return True
    if not isinstance(condition, dict):
        # Literal scalar / list — return as-is.
        return condition
    if len(condition) != 1:
        # Mixed dict — not a valid operator node; treat as truthy.
        logger.debug("condition with multiple keys, evaluating as truthy: %s", condition)
        return bool(condition)
    [(op, args)] = condition.items()
    handler = _OPS.get(op)
    if handler is None:
        logger.warning("unknown condition operator: %s", op)
        return False
    try:
        return handler(args, ctx)
    except Exception as exc:
        logger.warning("condition op %s(%r) failed: %s — defaulting to False", op, args, exc)
        return False


def _binop(fn):
    def runner(args, ctx):
        a = evaluate(args[0], ctx)
        b = evaluate(args[1], ctx)
        if a is None or b is None:
            return False
        return fn(a, b)
    return runner


def _is_truthy(args, ctx):
    """Single-arg truthiness check: ``{"truthy": {"var": "x"}}``."""
    return bool(evaluate(args[0] if isinstance(args, list) else args, ctx))


_OPS: dict[str, Callable[[Any, dict[str, Any]], Any]] = {
    "var":      lambda args, ctx: _resolve_var(args, ctx),
    "==":       _binop(lambda a, b: a == b),
    "!=":       _binop(lambda a, b: a != b),
    "<":        _binop(lambda a, b: float(a) < float(b)),
    ">":        _binop(lambda a, b: float(a) > float(b)),
    "<=":       _binop(lambda a, b: float(a) <= float(b)),
    ">=":       _binop(lambda a, b: float(a) >= float(b)),
    "and":      lambda args, ctx: all(bool(evaluate(a, ctx)) for a in args),
    "or":       lambda args, ctx: any(bool(evaluate(a, ctx)) for a in args),
    "not":      lambda args, ctx: not bool(evaluate(args[0] if isinstance(args, list) else args, ctx)),
    "in":       _binop(lambda a, b: a in b),
    "contains": _binop(lambda a, b: b in a),
    "truthy":   _is_truthy,
}


__all__ = ["evaluate"]
