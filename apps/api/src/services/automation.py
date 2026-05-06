"""In-process automation engine — replaces n8n.

Runs scheduled jobs (cron) inside the FastAPI process via APScheduler, sends
Slack notifications, and records every job firing in the `automation_log`
table. Deliberately self-contained so the platform is one compose, one
dashboard.

Job handlers
------------
* evolution_scheduler — kicks off an evolution run on cron.
* drift_detection    — compares latest two promoted generations and
                       flags benchmark drops > threshold.
* health_check       — pings postgres / redis / ollama.
* daily_report       — Slack summary of yesterday's runs + today's
                       champion.
* weekly_summary     — 7-day aggregate.
* auto_cleanup       — deletes discarded-adapter dirs older than N days
                       (never touches the promoted lineage chain).

If APScheduler isn't installed (older image), the module still imports —
the engine just no-ops `start()` and logs a warning, so the API stays
healthy until the next rebuild ships APScheduler.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from config.settings import settings
from services.lineage_db import LineageDB

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
    logger.warning("APScheduler not installed (%s) — automation engine will no-op.", _exc)

# Single instance the rest of the app talks to.
_ENGINE: "AutomationEngine | None" = None


def get_engine() -> "AutomationEngine | None":
    """Return the live AutomationEngine if `attach_engine` was called, else None.

    Routes import this so they don't need the app object.
    """
    return _ENGINE


def attach_engine(engine: "AutomationEngine") -> None:
    global _ENGINE
    _ENGINE = engine


# Default job set. Each entry is shipped on first boot; the handful of
# settings the user can change (enabled, cron, config) live in the DB and
# override these defaults at start time.
DEFAULT_JOBS: list[dict[str, Any]] = [
    {
        "job_id": "evolution_scheduler",
        "name": "Nightly Evolution",
        "cron": "0 2 * * *",
        "enabled": False,  # OFF until the user opts in
        "config": {
            "base_model": "meta-llama/Llama-3.2-3B-Instruct",
            "max_generations": 2,
            "max_samples": 1000,
            "lora_rank": 16,
            "batch_size": 2,
        },
    },
    {
        "job_id": "drift_detection",
        "name": "Drift Detection",
        "cron": "0 */6 * * *",
        "enabled": True,
        "config": {"threshold_pct": 5.0},
    },
    {
        "job_id": "health_check",
        "name": "Health Monitor",
        "cron": "*/15 * * * *",
        "enabled": True,
        "config": {},
    },
    {
        "job_id": "daily_report",
        "name": "Daily Report",
        "cron": "0 8 * * *",
        "enabled": False,
        "config": {},
    },
    {
        "job_id": "weekly_summary",
        "name": "Weekly Summary",
        "cron": "0 9 * * 0",
        "enabled": False,
        "config": {},
    },
    {
        "job_id": "auto_cleanup",
        "name": "Auto Cleanup",
        "cron": "0 3 * * 0",
        "enabled": True,
        "config": {"keep_days": 7},
    },
]


def _human_cron(expr: str) -> str:
    """Best-effort human label for cron expressions used by default jobs."""
    if not expr:
        return ""
    table = {
        "0 2 * * *":   "Daily at 2 AM",
        "0 */6 * * *": "Every 6 hours",
        "*/15 * * * *":"Every 15 minutes",
        "0 8 * * *":   "Daily at 8 AM",
        "0 9 * * 0":   "Sunday at 9 AM",
        "0 3 * * 0":   "Sunday at 3 AM",
    }
    return table.get(expr.strip(), expr)


class AutomationEngine:
    """One scheduler per FastAPI process. Owns Slack delivery + job dispatch."""

    def __init__(self, app):
        self.app = app
        self._scheduler = AsyncIOScheduler() if APSCHEDULER_AVAILABLE else None
        # Defensive: fall back to env if the DB row hasn't been read yet.
        self._slack_url_default = os.environ.get("SLACK_WEBHOOK_URL", "") or ""
        self._jobs: dict[str, dict[str, Any]] = {}
        self._handlers: dict[str, Callable[..., Awaitable[None]]] = {
            "evolution_scheduler": self._run_evolution,
            "drift_detection":     self._check_drift,
            "health_check":        self._health_check,
            "daily_report":        self._daily_report,
            "weekly_summary":      self._weekly_summary,
            "auto_cleanup":        self._auto_cleanup,
        }

    @property
    def db(self) -> LineageDB:
        return LineageDB(getattr(self.app.state, "db_pool", None))

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        if not APSCHEDULER_AVAILABLE or self._scheduler is None:
            logger.warning("automation.start: APScheduler missing, skipping")
            return
        # Seed default rows (idempotent) then load whatever the DB now has.
        try:
            db = self.db
            existing = {j["job_id"]: j for j in await db.list_automation_jobs()}
            for d in DEFAULT_JOBS:
                if d["job_id"] not in existing:
                    await db.upsert_automation_job(
                        job_id=d["job_id"],
                        name=d["name"],
                        cron=d["cron"],
                        enabled=d["enabled"],
                        config=d["config"],
                    )
            jobs = await db.list_automation_jobs()
        except Exception as exc:
            logger.warning("automation.start: DB load failed (%s) — using defaults", exc)
            jobs = DEFAULT_JOBS

        for job in jobs:
            self._jobs[job["job_id"]] = job
            if job.get("enabled"):
                self._add_to_scheduler(job)
        try:
            self._scheduler.start()
        except Exception as exc:
            logger.warning("automation.start: scheduler.start failed: %s", exc)
        active = sum(1 for j in self._jobs.values() if j.get("enabled"))
        logger.info("[automation] started with %d active jobs", active)

    async def stop(self) -> None:
        if self._scheduler:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception as exc:  # pragma: no cover
                logger.debug("scheduler.shutdown: %s", exc)

    def _add_to_scheduler(self, job: dict) -> None:
        if not self._scheduler or not CronTrigger:
            return
        handler = self._handlers.get(job["job_id"])
        if handler is None:
            logger.debug("no handler for job %s", job["job_id"])
            return
        try:
            self._scheduler.add_job(
                self._wrap(handler, job["job_id"]),
                CronTrigger.from_crontab(job["cron"]),
                id=job["job_id"],
                kwargs=job.get("config") or {},
                replace_existing=True,
                misfire_grace_time=600,
            )
        except Exception as exc:
            logger.warning("add_job(%s) failed: %s", job["job_id"], exc)

    def _remove_from_scheduler(self, job_id: str) -> None:
        if not self._scheduler:
            return
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass

    def _wrap(self, handler: Callable[..., Awaitable[None]], job_id: str) -> Callable[..., Awaitable[None]]:
        """Wrap a handler so its result is recorded to the automation_log row."""
        async def runner(**kwargs):
            try:
                await handler(**kwargs)
            except Exception as exc:
                logger.exception("[automation:%s] failed", job_id)
                try:
                    await self.db.record_automation_run(
                        job_id=job_id, status="error", message=str(exc)[:500],
                    )
                except Exception:
                    pass
        return runner

    # ── Public API ────────────────────────────────────────────────

    async def list_jobs(self) -> list[dict]:
        # Pull fresh from the DB so PUT updates are visible immediately.
        try:
            rows = await self.db.list_automation_jobs()
        except Exception as exc:
            logger.warning("list_jobs DB read failed: %s", exc)
            rows = list(self._jobs.values())
        out = []
        for j in rows:
            out.append({
                "job_id": j.get("job_id"),
                "name": j.get("name"),
                "cron": j.get("cron"),
                "cron_human": _human_cron(j.get("cron") or ""),
                "enabled": bool(j.get("enabled")),
                "config": j.get("config") or {},
                "last_run_at": j.get("last_run_at"),
                "last_run_status": j.get("last_run_status"),
                "last_run_message": j.get("last_run_message"),
            })
        return out

    async def update_job(
        self,
        job_id: str,
        *,
        enabled: bool | None = None,
        cron: str | None = None,
        config: dict | None = None,
    ) -> dict | None:
        current = await self.db.get_automation_job(job_id)
        if not current:
            # Allow creating from a default if the user enables before defaults seeded.
            for d in DEFAULT_JOBS:
                if d["job_id"] == job_id:
                    current = dict(d)
                    break
        if not current:
            return None
        new_enabled = bool(enabled) if enabled is not None else bool(current.get("enabled"))
        new_cron    = str(cron) if cron else current.get("cron") or ""
        new_config  = config if config is not None else (current.get("config") or {})
        saved = await self.db.upsert_automation_job(
            job_id=job_id,
            name=current.get("name") or job_id,
            cron=new_cron,
            enabled=new_enabled,
            config=new_config,
        )
        # Mirror into the live scheduler.
        self._jobs[job_id] = dict(saved or current)
        self._remove_from_scheduler(job_id)
        if new_enabled:
            self._add_to_scheduler(self._jobs[job_id])
        return saved

    async def trigger(self, job_id: str) -> bool:
        handler = self._handlers.get(job_id)
        if not handler:
            return False
        # Use the latest config from DB so a tweak applied right before
        # "Run Now" is honoured.
        job = await self.db.get_automation_job(job_id) or self._jobs.get(job_id) or {}
        cfg = (job.get("config") if isinstance(job, dict) else {}) or {}
        asyncio.create_task(self._wrap(handler, job_id)(**cfg))
        return True

    # ── Slack ─────────────────────────────────────────────────────

    async def _slack_url(self) -> str:
        try:
            settings_row = await self.db.get_automation_settings()
        except Exception:
            settings_row = None
        return (settings_row or {}).get("slack_webhook_url") or self._slack_url_default

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
        await self.db.record_automation_run(
            job_id=event_type or "notify", status="info", message=f"{emoji} {message}",
        )
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

    # ── Helpers (call services directly — no HTTP round-trip) ─────

    async def _evolve_status(self) -> dict:
        try:
            db = self.db
            row = await db.get_dashboard_run()
            return dict(row) if row else {}
        except Exception as exc:
            logger.debug("_evolve_status: %s", exc)
            return {}

    async def _scores_history(self) -> list[dict[str, float]]:
        """Return one dict per generation with bench → score, ordered oldest→newest."""
        try:
            gens = await self.db.get_all_generations(include_archived=False)
        except Exception:
            return []
        out: list[dict[str, float]] = []
        for g in sorted(gens or [], key=lambda r: int(r.get("generation") or 0)):
            cs = g.get("child_scores") or {}
            if isinstance(cs, str):
                import json as _json
                try: cs = _json.loads(cs)
                except Exception: cs = {}
            if isinstance(cs, dict) and cs:
                out.append({k: float(v) for k, v in cs.items() if isinstance(v, (int, float))})
        return out

    async def _champion(self) -> dict:
        # Read registry.json — same source the dashboard uses.
        try:
            from services.model_registry import ModelRegistry
            return ModelRegistry().get_champion() or {}
        except Exception as exc:
            logger.debug("_champion: %s", exc)
            return {}

    async def _runs(self) -> list[dict]:
        try:
            return await self.db.list_runs(limit=200)
        except Exception:
            return []

    # ── Job handlers ──────────────────────────────────────────────

    async def _run_evolution(self, **config) -> None:
        """Start a scheduled evolution run via the in-process orchestrator."""
        from agents import start_evolution  # avoids circular import
        from uuid import uuid4
        # Skip if a run is already active.
        status = await self._evolve_status()
        if status.get("status") in ("running", "starting"):
            await self.db.record_automation_run(
                job_id="evolution_scheduler",
                status="info",
                message=f"Skipped — run {status.get('run_id')} active",
            )
            return
        # Prepare a fresh run.
        run_id = f"run-{uuid4().hex[:8]}"
        try:
            await self.db.save_run(run_id, "starting", config)
            start_evolution(run_id, config, self.db)
        except Exception as exc:
            await self.notify(
                f"Scheduled evolution failed to start: {exc}", "🔴", event_type="evolution_failed",
            )
            return
        await self.notify(
            f"Scheduled evolution started: {config.get('base_model','default')} × "
            f"{config.get('max_generations', 2)} gen — run {run_id}",
            "🚀", event_type="evolution_started",
        )

    async def _check_drift(self, threshold_pct: float = 5.0, **kwargs) -> None:
        scores = await self._scores_history()
        if len(scores) < 2:
            await self.db.record_automation_run(
                job_id="drift_detection", status="info",
                message="Not enough data (need ≥2 generations)",
            )
            return
        latest, previous = scores[-1], scores[-2]
        drifts = []
        for bench, new_v in latest.items():
            old_v = previous.get(bench)
            if old_v is None:
                continue
            delta = float(new_v) - float(old_v)
            if delta < -(threshold_pct / 100):
                drifts.append(f"{bench}: {delta * 100:+.1f}%")
        if drifts:
            msg = f"Drift detected: {', '.join(drifts)}"
            await self.notify(msg, "⚠️", event_type="drift_detected")
        else:
            await self.db.record_automation_run(
                job_id="drift_detection", status="info",
                message="No drift — scores stable",
            )

    async def _health_check(self, **kwargs) -> None:
        # Inline checks so we don't HTTP-loop back through nginx.
        from config.redis_pool import get_redis
        results = {"postgres": "ok", "redis": "ok", "ollama": "ok"}
        try:
            db_ok = await self.db.ping()
            results["postgres"] = "ok" if db_ok else "down"
        except Exception:
            results["postgres"] = "down"
        try:
            r = await get_redis()
            await r.ping()
        except Exception:
            results["redis"] = "down"
        try:
            ollama_host = settings.ollama_host.rstrip("/")
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{ollama_host}/api/tags")
                results["ollama"] = "ok" if resp.status_code == 200 else "down"
        except Exception:
            results["ollama"] = "down"
        failed = [k for k, v in results.items() if v != "ok"]
        if failed:
            await self.notify(
                f"Services degraded: {', '.join(failed)}",
                "🔴", event_type="health_check",
            )
        else:
            await self.db.record_automation_run(
                job_id="health_check", status="info",
                message="All services healthy",
            )

    async def _daily_report(self, **kwargs) -> None:
        champion = await self._champion()
        runs = await self._runs()
        today = datetime.now(timezone.utc).date()
        today_runs = [r for r in runs if str(r.get("started_at") or "").startswith(str(today))]
        scores = champion.get("scores") or {}
        top_bench = max(scores.items(), key=lambda kv: kv[1]) if scores else ("?", 0)
        msg = (
            f"Daily Report — Champion gen {champion.get('generation','?')} "
            f"avg {champion.get('avg_score', 0):.3f}; "
            f"runs today: {len(today_runs)}; "
            f"top bench: {top_bench[0]} {float(top_bench[1]):.3f}"
        )
        await self.notify(msg, "📊", event_type="daily_report")

    async def _weekly_summary(self, **kwargs) -> None:
        runs = await self._runs()
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        recent = [
            r for r in runs
            if r.get("started_at") and (
                r["started_at"] if isinstance(r["started_at"], datetime)
                else datetime.fromisoformat(str(r["started_at"]).replace("Z", "+00:00"))
            ) >= cutoff
        ]
        promoted = sum(1 for r in recent if r.get("final_champion_score"))
        msg = (
            f"Weekly Summary — {len(recent)} runs in 7 days, "
            f"{promoted} produced a promoted champion."
        )
        await self.notify(msg, "📈", event_type="weekly_summary")

    async def _auto_cleanup(self, keep_days: int = 7, **kwargs) -> None:
        """Delete adapter dirs whose generation row is `discarded` and older than
        keep_days. Never deletes adapters in the promoted lineage chain."""
        try:
            data_root = settings.resolve_data_root()
            adapters_dir = Path(data_root) / "adapters"
            if not adapters_dir.is_dir():
                return
            promoted_paths: set[str] = set()
            try:
                gens = await self.db.get_all_generations()
            except Exception:
                gens = []
            for g in gens or []:
                if g.get("promoted") or g.get("is_champion"):
                    rid = str(g.get("run_id") or "")
                    if rid:
                        promoted_paths.add(f"{rid}__gen{int(g.get('generation') or 0)}")

            cutoff = datetime.now(timezone.utc) - timedelta(days=int(keep_days))
            deleted, freed_mb = 0, 0.0
            for run_dir in adapters_dir.iterdir():
                if not run_dir.is_dir():
                    continue
                for gen_dir in run_dir.iterdir():
                    if not gen_dir.is_dir() or not gen_dir.name.startswith("gen-"):
                        continue
                    try:
                        gen_n = int(gen_dir.name.replace("gen-", ""))
                    except ValueError:
                        continue
                    aid = f"{run_dir.name}__gen{gen_n}"
                    if aid in promoted_paths:
                        continue
                    mtime = datetime.fromtimestamp(gen_dir.stat().st_mtime, tz=timezone.utc)
                    if mtime > cutoff:
                        continue
                    size = sum(f.stat().st_size for f in gen_dir.rglob("*") if f.is_file())
                    freed_mb += size / (1024 * 1024)
                    shutil.rmtree(gen_dir, ignore_errors=True)
                    deleted += 1
            if deleted:
                await self.notify(
                    f"Cleaned up {deleted} old adapters, freed {freed_mb:.0f}MB",
                    "🧹", event_type="auto_cleanup",
                )
            else:
                await self.db.record_automation_run(
                    job_id="auto_cleanup", status="info",
                    message="Nothing to clean up",
                )
        except Exception as exc:
            await self.db.record_automation_run(
                job_id="auto_cleanup", status="error",
                message=f"Error: {exc}",
            )
