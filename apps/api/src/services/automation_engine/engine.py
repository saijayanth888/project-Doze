"""Workflow-aware automation engine.

Owns:

* the APScheduler instance for cron-triggered workflows,
* an event bus subscription that routes domain events to event-triggered
  workflows,
* the seeding of :data:`DEFAULT_WORKFLOWS` on first boot,
* the legacy ``notify()`` API still used by ``agents/runner.py``,
* webhook firing (route hands us the workflow id + parsed body).

The engine is a process-wide singleton — :func:`get_engine` returns the
attached instance, ``None`` if the lifespan handler hasn't constructed it
yet (e.g. early test imports).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any
from uuid import uuid4

import httpx

from config.settings import settings
from services.event_bus import Event, bus
from services.lineage_db import LineageDB

from .seeds import DEFAULT_WORKFLOWS
from .workflow_runner import execute_workflow

logger = logging.getLogger("modelforge.automation")

# Optional dep — gracefully degrade if not present yet.
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    APSCHEDULER_AVAILABLE = True
except Exception as _exc:  # pragma: no cover
    AsyncIOScheduler = None  # type: ignore
    CronTrigger = None       # type: ignore
    APSCHEDULER_AVAILABLE = False
    logger.warning("APScheduler not installed (%s) — engine will no-op.", _exc)


# ── Module-level singleton ────────────────────────────────────────────

_ENGINE: "AutomationEngine | None" = None


def get_engine() -> "AutomationEngine | None":
    return _ENGINE


def attach_engine(engine: "AutomationEngine") -> None:
    global _ENGINE
    _ENGINE = engine


# ── Backwards-compat constants ────────────────────────────────────────

# Kept so the legacy `/api/automation/jobs` route can still respond without
# crashing. The new workflow engine is the source of truth.
DEFAULT_JOBS: list[dict[str, Any]] = []


# ── Engine ────────────────────────────────────────────────────────────


class AutomationEngine:
    """One scheduler + event router per FastAPI process."""

    def __init__(self, app):
        self.app = app
        self._scheduler = AsyncIOScheduler() if APSCHEDULER_AVAILABLE else None
        self._slack_url_default = os.environ.get("SLACK_WEBHOOK_URL", "") or ""
        # workflow_id → APScheduler job_id mapping (cron only).
        self._cron_workflows: dict[str, str] = {}
        # workflow_id → bus subscription marker (we tag bus subs by workflow id).
        self._event_subscribed: set[str] = set()

    @property
    def db(self) -> LineageDB:
        return LineageDB(getattr(self.app.state, "db_pool", None))

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        if not APSCHEDULER_AVAILABLE or self._scheduler is None:
            logger.warning("automation.start: APScheduler missing, skipping")
            return
        try:
            await self._seed_defaults()
        except Exception as exc:
            logger.warning("automation.start: seeding failed: %s", exc)

        try:
            workflows = await self.db.list_workflows()
        except Exception as exc:
            logger.warning("automation.start: list_workflows failed: %s", exc)
            workflows = []

        for wf in workflows:
            self._mount(wf)

        try:
            self._scheduler.start()
        except Exception as exc:
            logger.warning("automation.start: scheduler.start failed: %s", exc)

        # Subscribe one wildcard handler so we can route ALL events without
        # re-registering subs each time a workflow is added/updated.
        bus.subscribe("*", self._on_event, name="automation_engine")

        active_cron = sum(1 for w in workflows if w.get("enabled") and w.get("trigger_type") == "cron")
        active_event = sum(1 for w in workflows if w.get("enabled") and w.get("trigger_type") == "event")
        logger.info(
            "[automation] started — %d workflow(s) total, %d cron / %d event active",
            len(workflows), active_cron, active_event,
        )

    async def stop(self) -> None:
        if self._scheduler:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception as exc:
                logger.debug("scheduler.shutdown: %s", exc)
        bus.unsubscribe_all(name="automation_engine")

    # ── Seeding ──────────────────────────────────────────────────────

    async def _seed_defaults(self) -> None:
        """Insert any seed workflow that isn't already in the DB by (kind, name)."""
        existing_names: set[str] = set()
        try:
            existing = await self.db.list_workflows(kind="system")
            existing_names = {str(w.get("name")) for w in existing}
        except Exception as exc:
            logger.debug("seed: list_workflows failed: %s", exc)
        for w in DEFAULT_WORKFLOWS:
            if w["name"] in existing_names:
                continue
            try:
                await self.db.create_workflow(
                    name=w["name"],
                    description=w.get("description"),
                    enabled=bool(w.get("enabled")),
                    kind="system",
                    trigger_type=str(w["trigger_type"]),
                    trigger_config=w.get("trigger_config") or {},
                    condition=w.get("condition"),
                    actions=list(w.get("actions") or []),
                )
                logger.info("[automation] seeded system workflow: %s", w["name"])
            except Exception as exc:
                logger.warning("[automation] seed failed for %s: %s", w["name"], exc)

    # ── Mount / unmount ──────────────────────────────────────────────

    def _mount(self, workflow: dict[str, Any]) -> None:
        """Register a workflow with the scheduler / event bus per its trigger."""
        wf_id = str(workflow.get("id"))
        if not wf_id:
            return
        if not workflow.get("enabled"):
            return
        ttype = str(workflow.get("trigger_type") or "")
        tcfg = workflow.get("trigger_config") or {}
        if ttype == "cron":
            self._mount_cron(wf_id, str(tcfg.get("cron") or ""))
        elif ttype == "event":
            # Event delivery is handled centrally in _on_event; we just record
            # that this workflow is "live" so we know to consider it.
            self._event_subscribed.add(wf_id)
        # webhook + manual: nothing to mount; routes call us explicitly.

    def _mount_cron(self, wf_id: str, cron_expr: str) -> None:
        if not self._scheduler or not CronTrigger:
            return
        if not cron_expr.strip():
            logger.warning("[automation] workflow %s missing cron expression", wf_id)
            return
        try:
            sched_id = f"wf:{wf_id}"
            self._scheduler.add_job(
                self._run_workflow_by_id,
                CronTrigger.from_crontab(cron_expr),
                id=sched_id,
                kwargs={"wf_id": wf_id, "trigger_kind": "cron", "payload": {}},
                replace_existing=True,
                misfire_grace_time=600,
            )
            self._cron_workflows[wf_id] = sched_id
        except Exception as exc:
            logger.warning("[automation] add_job(%s) failed: %s", wf_id, exc)

    def _unmount(self, workflow_id: str) -> None:
        sched_id = self._cron_workflows.pop(workflow_id, None)
        if sched_id and self._scheduler:
            try:
                self._scheduler.remove_job(sched_id)
            except Exception:
                pass
        self._event_subscribed.discard(workflow_id)

    def remount(self, workflow: dict[str, Any]) -> None:
        """Tear down the previous mount + remount (after a workflow update)."""
        wf_id = str(workflow.get("id"))
        self._unmount(wf_id)
        self._mount(workflow)

    # ── Event router (single wildcard sub on the bus) ────────────────

    async def _on_event(self, evt: Event) -> None:
        """Match this event against every event-triggered workflow's pattern.

        Triggered workflows fire in parallel; one bad workflow never blocks
        the others.
        """
        if not self._event_subscribed:
            return
        try:
            workflows = await self.db.list_workflows()
        except Exception:
            return
        import fnmatch
        firing: list[dict[str, Any]] = []
        for wf in workflows:
            if not wf.get("enabled"):
                continue
            if str(wf.get("trigger_type")) != "event":
                continue
            pattern = str((wf.get("trigger_config") or {}).get("pattern") or "")
            if not pattern:
                continue
            if fnmatch.fnmatchcase(evt.topic, pattern):
                firing.append(wf)
        if not firing:
            return
        await asyncio.gather(
            *(execute_workflow(
                workflow=wf,
                trigger_kind="event",
                trigger_payload={**evt.payload, "_event_topic": evt.topic, "_event_id": evt.id},
                engine=self,
              ) for wf in firing),
            return_exceptions=True,
        )

    # ── External entry points ────────────────────────────────────────

    async def _run_workflow_by_id(self, *, wf_id: str, trigger_kind: str, payload: dict) -> None:
        try:
            wf = await self.db.get_workflow(wf_id)
        except Exception as exc:
            logger.warning("run_workflow_by_id(%s): get_workflow failed: %s", wf_id, exc)
            return
        if not wf or not wf.get("enabled"):
            return
        try:
            await execute_workflow(
                workflow=wf, trigger_kind=trigger_kind, trigger_payload=payload, engine=self,
            )
        except Exception:
            logger.exception("workflow %s failed", wf_id)

    async def trigger_workflow(self, workflow_id: str, *, payload: dict | None = None,
                               trigger_kind: str = "manual") -> dict | None:
        """Manual fire — the route's 'Run now' button hits this."""
        wf = await self.db.get_workflow(workflow_id)
        if not wf:
            return None
        return await execute_workflow(
            workflow=wf, trigger_kind=trigger_kind,
            trigger_payload=payload or {}, engine=self,
        )

    async def fire_webhook(self, workflow_id: str, *, secret: str, body: dict | None) -> dict | None:
        """Webhook route hands us the parsed body; we verify the secret + run."""
        wf = await self.db.get_workflow(workflow_id)
        if not wf or wf.get("trigger_type") != "webhook" or not wf.get("enabled"):
            return None
        expected = str(wf.get("webhook_secret") or "")
        if not expected or expected != secret:
            return {"status": "denied", "reason": "secret_mismatch"}
        return await execute_workflow(
            workflow=wf, trigger_kind="webhook",
            trigger_payload=body or {}, engine=self,
        )

    @staticmethod
    def new_webhook_secret() -> str:
        """Generate a fresh url-safe secret for new webhook workflows."""
        return uuid4().hex + uuid4().hex[:8]  # 40 chars

    # ── Slack delivery (used by notify.slack action AND legacy notify()) ──

    async def _slack_url(self) -> str:
        try:
            row = await self.db.get_automation_settings()
        except Exception:
            row = None
        return (row or {}).get("slack_webhook_url") or self._slack_url_default

    async def _allowed_event(self, event_type: str | None) -> bool:
        if not event_type:
            return True
        try:
            row = await self.db.get_automation_settings()
        except Exception:
            row = None
        allow = (row or {}).get("notify_event_types") or []
        if not allow:
            return True
        return event_type in allow

    async def notify(self, message: str, emoji: str = "🔔", *, event_type: str | None = None) -> None:
        """Legacy API kept for ``agents/runner.py``. Writes to automation_log
        and posts to Slack subject to the per-event allow-list."""
        try:
            await self.db.record_automation_run(
                job_id=event_type or "notify", status="info", message=f"{emoji} {message}",
            )
        except Exception:
            pass
        if not await self._allowed_event(event_type):
            return
        url = await self._slack_url()
        if not url:
            return
        body = {"text": f"{emoji} *ModelForge* — {message}"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(url, json=body)
        except Exception as exc:
            logger.warning("[slack] failed: %s", exc)


__all__ = ["AutomationEngine", "DEFAULT_JOBS", "attach_engine", "get_engine"]
