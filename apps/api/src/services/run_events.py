"""Per-run, in-process ring buffer of human-readable phase events.

The orchestrator's `current_step` only updates when each LangGraph node
*finishes*. That meant the dashboard could sit on `train_adapter` for 3 hours
while the actual eval phase was running. This buffer plus the matching
`/api/evolve/{run_id}/events` route gives the UI a fine-grained timeline of
"what's happening right now" without exposing raw stdout / docker logs.

Design choices
--------------
* In-memory only. The lineage_db is the right home for *durable* generation
  records; this buffer is for live, small, transient run telemetry. Surviving
  an API restart is explicitly not a goal — the orchestrator's run dies on
  restart anyway, so the buffer dying with it is fine.
* Per-run cap (default 200) is generous enough for an entire 3-gen Llama 3B
  run while bounding memory.
* Each event has a monotonic ``id`` so the frontend can fetch only newly
  arrived events via ``since=``.
* No threading primitives needed — Python's ``deque.append`` and slicing are
  both atomic for our use, and we never call ``get`` from a different thread
  than ``publish``. (``run_in_executor`` callbacks publish, FastAPI handlers
  read.)
"""

from __future__ import annotations

import logging
import time
from collections import deque
from threading import Lock
from typing import Any

logger = logging.getLogger("modelforge.run_events")

_BUFFERS: dict[str, deque[dict[str, Any]]] = {}
_NEXT_ID: dict[str, int] = {}
_LOCK = Lock()
_PER_RUN_CAP = 200


def publish(
    run_id: str,
    *,
    phase: str,
    label: str,
    level: str = "info",
    sub: str | None = None,
    metric: dict[str, Any] | None = None,
    generation: int | None = None,
) -> None:
    """Append one event for ``run_id``. Safe to call from any backend thread.

    `phase` is a coarse identifier — "init" / "curate" / "train" / "eval" /
    "decide" / "error". `label` is the headline shown in the UI. `sub` is an
    optional second line. `metric` carries one or more numeric values
    (loss, accuracy, samples_per_sec) for inline mini-charts.
    """
    if not run_id:
        return
    rid = str(run_id)
    with _LOCK:
        buf = _BUFFERS.setdefault(rid, deque(maxlen=_PER_RUN_CAP))
        eid = _NEXT_ID.get(rid, 0)
        _NEXT_ID[rid] = eid + 1
        buf.append(
            {
                "id": eid,
                "ts": time.time(),
                "run_id": rid,
                "phase": str(phase),
                "level": str(level),
                "label": str(label),
                "sub": str(sub) if sub is not None else None,
                "metric": metric or None,
                "generation": int(generation) if generation is not None else None,
            }
        )


def list_events(run_id: str, *, since: int = -1, limit: int = 200) -> list[dict[str, Any]]:
    """Return events with ``id > since`` for ``run_id``, newest last."""
    rid = str(run_id)
    with _LOCK:
        buf = _BUFFERS.get(rid)
        if not buf:
            return []
        # `deque` doesn't support slicing — copy then filter.
        out = [e for e in list(buf) if e["id"] > since]
    return out[-int(limit):]


def reset_run(run_id: str) -> None:
    """Drop all events for ``run_id`` — call when a run starts so a re-used id
    doesn't show stale data."""
    rid = str(run_id)
    with _LOCK:
        _BUFFERS.pop(rid, None)
        _NEXT_ID.pop(rid, None)
