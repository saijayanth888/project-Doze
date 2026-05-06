"""In-process pub/sub bus for domain events.

Used by the workflow engine: workflows whose trigger is `event` subscribe
to a topic pattern (`evolution.completed`, `champion.*`, …) and fire when
a matching event is published. This is the bridge between the evolution
loop's lifecycle and user-defined automations.

Design choices
--------------
- Topics are dot-separated strings (`evolution.completed`).
- Subscribers register a pattern with one trailing wildcard (`evolution.*`).
  No deep-glob, no regex — keeps the matcher predictable.
- All delivery is async, fire-and-forget. A slow subscriber never blocks
  the publisher; an exception in one subscriber never affects others.
- Single global instance; routes/services import `bus`.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

logger = logging.getLogger("modelforge.event_bus")

EventHandler = Callable[["Event"], Awaitable[None]]


@dataclass
class Event:
    topic: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "topic": self.topic,
            "payload": self.payload,
            "ts": self.ts.isoformat(),
        }


@dataclass
class _Subscription:
    pattern: str           # e.g. "evolution.*"
    handler: EventHandler
    name: str              # for diagnostics


class EventBus:
    def __init__(self) -> None:
        self._subs: list[_Subscription] = []

    # ── Public ─────────────────────────────────────────────────────

    def subscribe(self, pattern: str, handler: EventHandler, *, name: str = "anon") -> str:
        """Register a handler for events whose topic matches `pattern`.

        Patterns use shell-glob style (``fnmatch``):
          - exact match: `evolution.completed`
          - one segment wildcard: `evolution.*`
          - all events: `*`
        Returns a subscription id usable with :meth:`unsubscribe`.
        """
        sub = _Subscription(pattern=pattern, handler=handler, name=name)
        self._subs.append(sub)
        sub_id = f"{pattern}#{id(handler):x}"
        logger.debug("[event_bus] subscribed name=%s pattern=%s", name, pattern)
        return sub_id

    def unsubscribe_all(self, *, name: str | None = None, pattern: str | None = None) -> int:
        """Remove subscriptions matching the given name and/or pattern. Returns count removed."""
        before = len(self._subs)
        self._subs = [
            s for s in self._subs
            if (name is not None and s.name != name)
            or (pattern is not None and s.pattern != pattern)
            or (name is None and pattern is None)
        ]
        # Edge: when both name and pattern are None, the comprehension above keeps everything;
        # treat that as an explicit "wipe all" call.
        if name is None and pattern is None:
            self._subs = []
        return before - len(self._subs)

    async def publish(self, topic: str, payload: dict[str, Any] | None = None) -> Event:
        evt = Event(topic=topic, payload=payload or {})
        matches = [s for s in self._subs if fnmatch.fnmatchcase(topic, s.pattern)]
        if matches:
            logger.info(
                "[event_bus] publish topic=%s matches=%d payload_keys=%s",
                topic, len(matches), list((payload or {}).keys()),
            )
            # Fire all handlers in parallel; isolate failures per handler.
            await asyncio.gather(
                *(self._safe_call(s, evt) for s in matches),
                return_exceptions=True,
            )
        else:
            logger.debug("[event_bus] publish topic=%s no subscribers", topic)
        return evt

    def publish_nowait(self, topic: str, payload: dict[str, Any] | None = None) -> None:
        """Schedule a publish without awaiting it. Safe to call from sync code as long as
        an event loop is running."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("[event_bus] publish_nowait(%s) — no running loop, dropped", topic)
            return
        loop.create_task(self.publish(topic, payload))

    def list_subscriptions(self) -> list[dict[str, str]]:
        return [{"name": s.name, "pattern": s.pattern} for s in self._subs]

    # ── Internals ──────────────────────────────────────────────────

    async def _safe_call(self, sub: _Subscription, evt: Event) -> None:
        try:
            await sub.handler(evt)
        except Exception as exc:
            logger.exception("[event_bus] handler %s for pattern %s raised: %s",
                             sub.name, sub.pattern, exc)


# Module-level singleton — services and routes import this directly.
bus = EventBus()


__all__ = ["Event", "EventBus", "EventHandler", "bus"]
