"""Campaign Runner — sequential autopilot for multi-experiment campaigns.

Reads a list of experiment configs (from services.campaign_configs.CAMPAIGNS),
executes them one at a time, persists per-experiment results, sends a Slack
notification on each transition, and continues through failures (retry once,
then skip). Designed to run autonomously for hours/days while a researcher
checks progress via Slack each morning.

Singleton model: import `get_campaign_runner()`. Lifecycle is controlled
via the /api/campaigns/{id}/start, /pause, /resume, /stop endpoints.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

# Path to the eval subprocess worker (set in the Dockerfile via WORKDIR=/app
# + COPY apps/api/src/ ./src/). Each baseline experiment spawns a fresh
# instance so the OS reclaims all CUDA / Python memory on exit — see the
# project_dgx_freeze_fingerprint memory for why in-process gc.collect() +
# torch.cuda.empty_cache() leak 1-5 GB per model and crash the host.
_EVAL_WORKER_PATH = "/app/src/scripts/eval_worker.py"

logger = logging.getLogger("modelforge.services.campaign_runner")

# Cooldown between experiments — gives the GPU a chance to release fragmented
# blocks and lets the OS settle. 5 minutes is overkill for small experiments
# but cheap insurance for the multi-day 4-week campaign mode.
_COOLDOWN_SECONDS = 300

# Max wall time we'll wait for one experiment before timing out and
# moving on. 6 hours covers a 5-gen run on a 7B model.
_EXPERIMENT_TIMEOUT_SECONDS = 6 * 60 * 60

# Polling interval while waiting for a sequential run to finish.
_POLL_INTERVAL_SECONDS = 30

# Cooperative stop only checks `should_stop` at benchmark boundaries (lm-eval
# is one big sync call we can't interrupt mid-task). On a 7B model an MMLU or
# HumanEval run can take 30 min, so a click on Stop in the UI looks dead. After
# this many seconds in `stopping`, escalate to force_stop() automatically so
# the user doesn't have to discover the Force Stop button. 60s gives a real
# benchmark boundary a chance to fire while still feeling responsive.
_STOP_DEADLINE_SECONDS = 60


class CampaignRunner:
    run_kind: str = "campaign"

    def __init__(self) -> None:
        self.active_plan_id: str | None = None
        self.run_id: str | None = None  # synthetic id "camp-<plan_id>-<short>"
        self.status: str = "idle"  # idle | ensuring | running | paused | stopping
        self.current_experiment_index: int = 0
        self.results: list[dict[str, Any]] = []
        self._task: asyncio.Task | None = None
        # Auto-escalation watchdog scheduled by stop(): force-stops if the
        # cooperative stop is still pending after _STOP_DEADLINE_SECONDS.
        self._stop_watchdog: asyncio.Task | None = None
        # Active eval-worker subprocess (set while a baseline experiment is
        # running; force_stop() SIGTERMs it for guaranteed memory reclaim).
        self._eval_subprocess: asyncio.subprocess.Process | None = None
        self._experiments: list[dict] = []
        # Per-repo pre-flight download state, surfaced via get_status() so the
        # dashboard banner can show live progress while weights download.
        self.ensure_progress: list[dict[str, Any]] = []
        # Live "what is the runner doing right now" hints. Updated by the eval
        # backend at each benchmark boundary so the dashboard isn't a black
        # box during a 30-min experiment.
        self.current_model: str | None = None
        self.current_benchmark: str | None = None
        self.current_method: str | None = None
        self.current_started_at: float | None = None
        self.campaign_started_at: float | None = None
        # Per-experiment benchmark ladder, reset between experiments. Each entry:
        # {name, status: "queued"|"running"|"done"|"error", score?, stderr?}
        self.current_benchmarks: list[dict[str, Any]] = []
        # In-memory ring buffer of campaign events surfaced to the dashboard's
        # Activity Feed via /api/lineage/activity. Capped — only used for the
        # most recent ~100 events; full history lives in postgres.
        self.events: list[dict[str, Any]] = []
        self._event_seq: int = 0

    def _log_event(self, type_: str, message: str, **extra: Any) -> None:
        self._event_seq += 1
        evt = {
            "id": f"evt-camp-{self._event_seq}",
            "type": type_,
            "event": message,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "plan_id": self.active_plan_id,
            "run_id": self.run_id,
            **extra,
        }
        self.events.append(evt)
        if len(self.events) > 100:
            self.events = self.events[-100:]

        # Mirror onto the per-run ring buffer so /api/evolve/{run_id}/events
        # serves campaign events too — same transport as manual evolution runs.
        if self.run_id:
            try:
                from services import run_events
                run_events.publish(
                    self.run_id,
                    phase=self._phase_for(type_),
                    label=message,
                    level=("error" if "fail" in type_ or "error" in type_ else "info"),
                    sub=extra.get("model") or extra.get("benchmark") or extra.get("repo_id"),
                    metric=(
                        {"score": extra["score"]} if isinstance(extra.get("score"), (int, float)) else None
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("[campaign] run_events publish failed: %s", exc)

        # Publish to event_bus so workflow triggers + the Slack subscriber fire.
        try:
            from services.event_bus import bus
            bus.publish_nowait(f"campaign.{type_}", evt)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[campaign] event_bus publish failed: %s", exc)

    @staticmethod
    def _phase_for(event_type: str) -> str:
        if event_type.startswith("model_download"):
            return "ensure"
        if event_type.startswith("campaign"):
            return event_type.replace("campaign_", "campaign.")
        if event_type.startswith("experiment"):
            return "experiment"
        if event_type.startswith("benchmark"):
            return "evaluate"
        return event_type

    # ── Public lifecycle ────────────────────────────────────────

    async def start(self, plan_id: str, experiments: list[dict], db) -> dict:
        if self.status in ("running", "ensuring"):
            raise ValueError("a campaign is already running")
        self.active_plan_id = plan_id
        # Synthetic run_id ride: campaigns flow through the same /api/evolve/
        # {run_id}/events route + run_events ring buffer that manual evolution
        # uses, so dashboard widgets stay agnostic.
        self.run_id = f"camp-{plan_id}-{uuid.uuid4().hex[:8]}"
        try:
            from services import run_events
            run_events.reset_run(self.run_id)
        except Exception:
            pass
        # Mark "ensuring" so the UI shows the pre-flight phase before any
        # experiment kicks off; the runner flips to "running" once downloads
        # complete.
        self.status = "ensuring"
        self.current_experiment_index = 0
        self.results = []
        self.ensure_progress = []
        self.events = []
        self._event_seq = 0
        self.current_benchmarks = []
        self.campaign_started_at = time.time()
        self._experiments = list(experiments)
        self._log_event(
            "campaign_started",
            f"Campaign {plan_id} started · {len(experiments)} experiment(s)",
            total_experiments=len(experiments),
            experiments=[
                {
                    "model": e.get("model") or e.get("base_model"),
                    "method": e.get("method") or ("eval_only" if e.get("eval_only") else "sequential"),
                    "max_generations": e.get("max_generations"),
                }
                for e in experiments
            ],
        )

        # Persist the plan header.
        if db and getattr(db, "_pool", None):
            async with db._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO campaign_plans (plan_id, name, experiments, status, started_at)
                    VALUES ($1, $2, $3::jsonb, 'running', NOW())
                    ON CONFLICT (plan_id) DO UPDATE SET
                        status = 'running', started_at = NOW(), experiments = EXCLUDED.experiments
                    """,
                    plan_id, plan_id, json.dumps(experiments),
                )

        self._task = asyncio.create_task(
            self._run_campaign(experiments, db), name=f"campaign:{plan_id}"
        )
        return {
            "plan_id": plan_id,
            "status": "started",
            "total_experiments": len(experiments),
        }

    def pause(self) -> None:
        if self.status == "running":
            self.status = "paused"

    def resume(self) -> None:
        if self.status == "paused":
            self.status = "running"

    def stop(self) -> None:
        if self.status in ("running", "paused", "ensuring"):
            self.status = "stopping"
            # Schedule the deadline watchdog. If the cooperative stop hasn't
            # transitioned us to idle by _STOP_DEADLINE_SECONDS (e.g. lm-eval
            # is mid-task and won't yield until the next benchmark boundary),
            # the watchdog calls force_stop() so the UI doesn't appear wedged.
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                # Cancel any prior pending watchdog before scheduling a new one
                # (e.g. user clicked Stop, then Resume, then Stop again).
                if self._stop_watchdog is not None and not self._stop_watchdog.done():
                    self._stop_watchdog.cancel()
                self._stop_watchdog = loop.create_task(self._stop_deadline_watchdog())

    async def _stop_deadline_watchdog(self) -> None:
        """Auto-escalate cooperative stop to force-stop after the deadline.

        lm-eval's `simple_evaluate` is a sync call we can't interrupt — the
        runner only checks `should_stop` between benchmarks. On a long task
        (MMLU on a 7B, HumanEval on any model) that boundary can be 10–30 min
        away, during which the UI shows `stopping` and looks dead.

        This watchdog gives the cooperative path one minute (a real benchmark
        boundary often falls within that window), then force-stops if we're
        still wedged. force_stop() resets the runner to idle and cancels the
        asyncio task; the lm-eval thread keeps running in the executor pool
        until it returns naturally, but its result is dropped.
        """
        try:
            await asyncio.sleep(_STOP_DEADLINE_SECONDS)
        except asyncio.CancelledError:
            return
        if self.status == "stopping":
            logger.warning(
                "[campaign] cooperative stop wedged for %ds — auto-escalating to force_stop",
                _STOP_DEADLINE_SECONDS,
            )
            self.force_stop()

    def force_stop(self) -> dict[str, Any]:
        """Aggressively reset runner state without waiting for the current
        benchmark to finish.

        Cooperative stop ``stop()`` only engages at the next benchmark
        boundary, which can be 5–30 min for some lm-eval tasks. While we
        wait, Start is disabled and the dashboard shows ``stopping`` —
        users perceive the system as wedged.

        Force-stop cancels the asyncio campaign task, marks the runner
        ``idle``, and clears state so a new campaign can start
        immediately. The underlying lm-eval thread keeps running in the
        executor pool (Python can't kill threads) but its result is
        dropped on the floor and the GPU frees once the thread returns.
        """
        cancelled = False
        plan_id = self.active_plan_id
        if self._task and not self._task.done():
            try:
                self._task.cancel()
                cancelled = True
            except Exception:
                pass
        # Signal any in-flight lm-eval thread to abort at its next forward
        # pass — covers the legacy in-process path still used by EPT and
        # sequential evolution. The eval-subprocess path (campaign baseline)
        # is terminated separately below.
        try:
            from agents.eval_backend import request_eval_abort
            request_eval_abort()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[campaign] eval abort signal skipped: %s", exc)
        # Kill the eval-worker subprocess if one is alive. We schedule the
        # async terminate as a fire-and-forget task because force_stop() is
        # synchronous (called from the HTTP handler). The asyncio loop runs
        # _terminate_eval_subprocess on the next tick, sends SIGTERM with a
        # 5s grace, then SIGKILL — guaranteed memory reclaim.
        if self._eval_subprocess is not None and self._eval_subprocess.returncode is None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._terminate_eval_subprocess())
            except RuntimeError:
                logger.debug("[campaign] no running loop; cannot async-terminate eval subprocess")
        # Clean up the stop deadline watchdog if it's still pending — happens
        # when force_stop is invoked manually before the auto-escalation fires.
        if self._stop_watchdog is not None and not self._stop_watchdog.done():
            try:
                self._stop_watchdog.cancel()
            except Exception:
                pass
        self._stop_watchdog = None
        self.status = "idle"
        self.current_model = None
        self.current_benchmark = None
        self.current_benchmarks = []
        self.current_method = None
        self.current_started_at = None
        self.campaign_started_at = None
        # Leave run_id, results, ensure_progress, events alone so the
        # final dashboard snapshot remains readable. They'll be overwritten
        # when the next campaign starts.
        self._log_event(
            "campaign_force_stopped",
            f"Campaign {plan_id} force-stopped by user — runner reset, lm-eval thread will drain in background",
            cancelled_task=cancelled,
        )
        return {"status": "idle", "task_cancelled": cancelled, "plan_id": plan_id}

    def get_status(self) -> dict:
        completed = sum(1 for r in self.results if "completed" in (r.get("status") or ""))
        failed = sum(1 for r in self.results if (r.get("status") or "") == "failed")
        total = len(self._experiments) or 0
        elapsed = (
            time.time() - self.current_started_at
            if self.current_started_at is not None
            else None
        )
        # Whole-campaign elapsed (separate from current_elapsed_seconds which
        # is current-experiment elapsed).
        campaign_elapsed = (
            time.time() - self.campaign_started_at
            if self.campaign_started_at is not None
            else None
        )
        # ETA: pace-based projection from completed experiments.
        eta_seconds: float | None = None
        pace_avg: float | None = None
        finished = [r for r in self.results if r.get("duration") is not None]
        if finished:
            durations = [float(r["duration"]) for r in finished]
            pace_avg = sum(durations) / len(durations)
            remaining = max(0, total - (completed + failed))
            eta_seconds = pace_avg * remaining
        return {
            "status": self.status,
            "run_id": self.run_id,
            "run_kind": self.__class__.run_kind,
            "plan_id": self.active_plan_id,
            "current_experiment": self.current_experiment_index,
            "total_experiments": total,
            "completed": completed,
            "failed": failed,
            "results": self.results,
            "experiments": list(self._experiments),
            "ensure_progress": list(self.ensure_progress),
            "current_model": self.current_model,
            "current_benchmark": self.current_benchmark,
            "current_benchmarks": list(self.current_benchmarks),
            "current_method": self.current_method,
            "current_elapsed_seconds": elapsed,
            "campaign_elapsed_seconds": campaign_elapsed,
            "eta_seconds": eta_seconds,
            "pace_avg_seconds": pace_avg,
            "events": list(self.events[-20:]),
        }

    # ── Internals ────────────────────────────────────────────────

    async def _run_campaign(self, experiments: list[dict], db) -> None:
        total = len(experiments)

        # Pre-flight: ensure every referenced HF repo is cached locally so the
        # campaign can run end-to-end without anyone running `huggingface-cli
        # download` by hand. Failures here abort the campaign cleanly.
        async def _on_ensure_progress(item: dict) -> None:
            prev_status: str | None = None
            for entry in self.ensure_progress:
                if entry.get("repo_id") == item.get("repo_id"):
                    prev_status = entry.get("status")
                    entry.update(item)
                    break
            else:
                self.ensure_progress.append(dict(item))
            new_status = item.get("status")
            repo = item.get("repo_id")
            # Only log at state transitions to avoid spamming events on every
            # 2 s byte-poll while a download is in flight.
            if repo and new_status and new_status != prev_status:
                if new_status == "downloading":
                    self._log_event("model_download_started", f"Downloading {repo}", repo_id=repo)
                elif new_status == "done":
                    if not item.get("cached"):
                        self._log_event("model_download_complete", f"Downloaded {repo}", repo_id=repo)
                elif new_status == "error":
                    self._log_event(
                        "model_download_error",
                        f"Download failed: {repo} ({item.get('error', '')})",
                        repo_id=repo,
                    )

        try:
            from services.model_ensure import ensure_all_for_experiments
            await ensure_all_for_experiments(
                experiments, notify=self._notify, progress=_on_ensure_progress
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("[campaign] pre-flight model download failed: %s", exc)
            await self._notify(
                f"Campaign aborted before start — model download failed: {exc}",
                "🔴",
            )
            plan_id = self.active_plan_id
            self.status = "idle"
            if db and getattr(db, "_pool", None) and plan_id:
                async with db._pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE campaign_plans SET status = $1, completed_at = NOW() WHERE plan_id = $2",
                        "failed", plan_id,
                    )
            return

        # Pre-flight done — flip into the executing phase.
        if self.status == "ensuring":
            self.status = "running"

        for idx, exp in enumerate(experiments):
            if self.status == "stopping":
                logger.info("[campaign] stopped at experiment %d/%d", idx + 1, total)
                break
            while self.status == "paused":
                await asyncio.sleep(5)
                if self.status == "stopping":
                    break
            if self.status == "stopping":
                break

            # DRAM gate: GPU allocs on DGX Spark unified memory bypass cgroups,
            # so a low-DRAM start silently freezes the host instead of OOM-ing.
            # Wait once, then skip the experiment if we still can't fit.
            import psutil
            mem = psutil.virtual_memory()
            available_gb = mem.available / 1e9
            logger.info(
                "[campaign] Memory before exp %d: %.1fGB available",
                idx + 1, available_gb,
            )
            if available_gb < 20:
                logger.warning(
                    "[campaign] Only %.1fGB available, waiting 60s...",
                    available_gb,
                )
                await asyncio.sleep(60)
                mem = psutil.virtual_memory()
                available_gb = mem.available / 1e9
                if available_gb < 15:
                    logger.error(
                        "[campaign] ABORT: %.1fGB after wait, skipping experiment %d",
                        available_gb, idx + 1,
                    )
                    skipped_model = exp.get("model") or exp.get("base_model") or ""
                    self.results.append({
                        "index": idx,
                        "status": "failed",
                        "error": f"skipped — only {available_gb:.1f}GB DRAM available",
                    })
                    await self._db_upsert_result(db, idx, exp, status="failed", started=True)
                    await self._db_finish_result(
                        db, idx, status="failed",
                        error=f"skipped — only {available_gb:.1f}GB DRAM available",
                    )
                    self._log_event(
                        "experiment_failed",
                        f"Experiment {idx + 1}/{total} skipped — only {available_gb:.1f}GB DRAM available",
                        experiment_index=idx,
                        total_experiments=total,
                        model=skipped_model,
                        error=f"insufficient DRAM ({available_gb:.1f}GB)",
                    )
                    await self._notify(
                        f"Experiment {idx + 1}/{total} skipped — only {available_gb:.1f}GB DRAM available",
                        "🟠",
                    )
                    continue

            self.current_experiment_index = idx
            model = exp.get("model") or exp.get("base_model") or ""
            method = exp.get("method") or ("eval_only" if exp.get("eval_only") else "sequential")

            # Reset live-progress hints at each experiment boundary so the
            # dashboard reflects the new model immediately, not the old one.
            self.current_model = model
            self.current_method = method
            self.current_benchmark = None
            self.current_started_at = time.time()
            # Seed the benchmark ladder for eval-only experiments so the
            # dashboard renders the full set up front (queued → running → done).
            if exp.get("eval_only"):
                from agents.eval_backend import _BENCHMARKS
                self.current_benchmarks = [
                    {"name": b, "status": "queued"} for b in _BENCHMARKS
                ]
            else:
                self.current_benchmarks = []

            short = model.split("/")[-1] or model
            self._log_event(
                "experiment_started",
                f"Experiment {idx + 1}/{total} · {method} on {short}",
                experiment_index=idx,
                model=model,
                method=method,
            )
            await self._notify(
                f"Experiment {idx + 1}/{total} starting: {method} on {short}",
                "🧪",
            )
            await self._db_upsert_result(db, idx, exp, status="running", started=True)

            try:
                result = await self._run_single_experiment(exp, db, idx)
                self.results.append({"index": idx, "status": "completed", **result})
                await self._db_finish_result(db, idx, status="completed",
                                              scores=result.get("scores", {}),
                                              duration=result.get("duration", 0.0))
                avg = result.get("avg_score", 0.0)
                # ETA snapshot for the Slack card based on completed durations.
                durations = [
                    float(r.get("duration") or 0.0)
                    for r in self.results
                    if r.get("duration") is not None
                ]
                pace = (sum(durations) / len(durations)) if durations else 0.0
                remaining = max(0, total - (idx + 1))
                eta_seconds = pace * remaining if pace > 0 else None
                running_completed = sum(
                    1 for r in self.results if "completed" in (r.get("status") or "")
                )
                running_failed = sum(
                    1 for r in self.results if (r.get("status") or "") == "failed"
                )
                self._log_event(
                    "experiment_complete",
                    f"Experiment {idx + 1}/{total} complete · avg={avg:.3f}",
                    experiment_index=idx,
                    total_experiments=total,
                    model=model,
                    method=method,
                    avg_score=float(avg),
                    scores=result.get("scores", {}),
                    stderrs=result.get("stderrs", {}),
                    duration=result.get("duration", 0.0),
                    pace_avg_seconds=pace,
                    eta_seconds=eta_seconds,
                    completed=running_completed,
                    failed=running_failed,
                )
                await self._notify(
                    f"Experiment {idx + 1}/{total} complete · avg={avg:.3f}",
                    "✅",
                )
            except Exception as exc:  # noqa: BLE001 — fault-tolerant runner
                # Cooperative stop: don't retry, mark stopped, exit the loop.
                from agents.eval_backend import EvalStopped
                if isinstance(exc, EvalStopped) or self.status == "stopping":
                    logger.info("[campaign] exp %d stopped by user request", idx + 1)
                    self.results.append({"index": idx, "status": "stopped"})
                    await self._db_finish_result(db, idx, status="failed", error="stopped by user")
                    self._log_event(
                        "experiment_stopped",
                        f"Experiment {idx + 1}/{total} stopped by user",
                        experiment_index=idx,
                    )
                    await self._notify(
                        f"Experiment {idx + 1}/{total} stopped by user", "🛑",
                    )
                    await self._cleanup_gpu()
                    break
                logger.exception("[campaign] exp %d failed: %s", idx + 1, exc)
                await self._cleanup_gpu()
                # Retry once.
                try:
                    await asyncio.sleep(30)
                    result = await self._run_single_experiment(exp, db, idx)
                    self.results.append({"index": idx, "status": "completed_retry", **result})
                    await self._db_finish_result(db, idx, status="completed",
                                                  scores=result.get("scores", {}),
                                                  duration=result.get("duration", 0.0))
                    await self._notify(
                        f"Experiment {idx + 1}/{total} recovered after retry",
                        "🟡",
                    )
                except Exception as exc2:  # noqa: BLE001
                    logger.exception("[campaign] exp %d retry failed: %s", idx + 1, exc2)
                    self.results.append({"index": idx, "status": "failed", "error": str(exc2)})
                    await self._db_finish_result(db, idx, status="failed", error=str(exc2))
                    self._log_event(
                        "experiment_failed",
                        f"Experiment {idx + 1}/{total} FAILED: {str(exc2)[:160]}",
                        experiment_index=idx,
                        total_experiments=total,
                        model=model,
                        error=str(exc2)[:500],
                    )
                    await self._notify(
                        f"Experiment {idx + 1}/{total} FAILED after retry: {str(exc2)[:160]}",
                        "🔴",
                    )

            await self._cleanup_gpu()
            if idx < total - 1 and self.status not in ("stopping",):
                logger.info("[campaign] cooldown %ds before next experiment", _COOLDOWN_SECONDS)
                # Sleep in small chunks so pause/stop responds quickly.
                slept = 0
                while slept < _COOLDOWN_SECONDS and self.status not in ("stopping",):
                    while self.status == "paused":
                        await asyncio.sleep(2)
                    await asyncio.sleep(2)
                    slept += 2

        # Wrap up.
        completed = sum(1 for r in self.results if "completed" in (r.get("status") or ""))
        failed = sum(1 for r in self.results if (r.get("status") or "") == "failed")
        plan_id = self.active_plan_id
        # Build top-results ranking for the Slack summary card.
        ranked: list[dict[str, Any]] = []
        for r in self.results:
            if "completed" not in (r.get("status") or ""):
                ranked.append({
                    "model": (r.get("config") or {}).get("model")
                             or (self._experiments[r.get("index", 0)] if 0 <= r.get("index", 0) < len(self._experiments) else {}).get("model"),
                    "avg_score": None,
                    "status": r.get("status"),
                    "error": r.get("error"),
                })
                continue
            ranked.append({
                "model": (
                    self._experiments[r.get("index", 0)]
                    if 0 <= r.get("index", 0) < len(self._experiments)
                    else {}
                ).get("model"),
                "avg_score": float(r.get("avg_score") or 0.0),
                "scores": r.get("scores") or {},
                "duration": float(r.get("duration") or 0.0),
                "status": "completed",
            })
        # Sort succeeded first (by avg desc), then failures.
        ranked.sort(
            key=lambda x: (
                0 if x.get("avg_score") is not None else 1,
                -(x.get("avg_score") or 0.0),
            )
        )
        total_dur = (
            time.time() - self.campaign_started_at
            if self.campaign_started_at is not None
            else 0.0
        )
        self.status = "idle"
        self.current_model = None
        self.current_benchmark = None
        self.current_method = None
        self.current_started_at = None
        self.current_benchmarks = []
        self.campaign_started_at = None
        if db and getattr(db, "_pool", None) and plan_id:
            async with db._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE campaign_plans SET status = $1, completed_at = NOW() WHERE plan_id = $2",
                    "completed" if completed + failed == total else "stopped",
                    plan_id,
                )
        self._log_event(
            "campaign_complete",
            f"Campaign {plan_id} complete · {completed}/{total} succeeded · {failed} failed",
            completed=completed,
            failed=failed,
            total=total,
            top_results=ranked,
            total_duration_seconds=total_dur,
        )
        await self._notify(
            f"Campaign complete · {completed}/{total} succeeded · {failed} failed",
            "🏁",
        )

    async def _run_eval_subprocess(self, exp: dict, model: str, idx: int) -> dict:
        """Spawn `eval_worker.py` for one model and stream its progress events.

        Subprocess isolation is the only way to fully reclaim CUDA memory on
        the DGX Spark unified-memory architecture: in-process gc.collect() +
        torch.cuda.empty_cache() leak 1-5 GB of allocator state per model,
        which after 4-5 baseline runs causes a silent host freeze (NVRM
        `_memdescAllocInternal` runs out of host pages, no OOM-killer fires).
        Process exit reclaims everything atomically.
        """
        from agents.eval_backend import _BENCHMARKS

        run_id = f"baseline-{uuid.uuid4().hex[:8]}"
        short = (model or "").split("/")[-1] or model or "?"
        bench_list = exp.get("benchmarks") or list(_BENCHMARKS)
        if not isinstance(bench_list, list):
            bench_list = list(_BENCHMARKS)
        benchmarks_arg = ",".join(bench_list)

        output_path = f"/tmp/eval-{run_id}.json"
        cmd = [
            "python",
            _EVAL_WORKER_PATH,
            "--model", model,
            "--output", output_path,
            "--benchmarks", benchmarks_arg,
        ]
        eval_limit = exp.get("eval_limit") or exp.get("limit")
        if isinstance(eval_limit, int) and eval_limit > 0:
            cmd.extend(["--limit", str(eval_limit)])

        logger.info("[campaign] spawning eval-worker for %s: %s", short, " ".join(cmd))
        t0 = time.perf_counter()

        # argv-list form (no shell); cmd values come from the campaign config,
        # not user input, so there is no injection surface.
        # 10 MiB readline buffer: lm-eval's tqdm progress emits \r updates that
        # accumulate past the 64 KiB default before a \n arrives — readline
        # would otherwise raise LimitOverrunError mid-benchmark.
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=10 * 1024 * 1024,
        )
        self._eval_subprocess = proc

        async def _consume_stdout() -> None:
            assert proc.stdout is not None
            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    return
                line = line_bytes.decode(errors="replace").rstrip()
                if not line:
                    continue
                if not line.startswith("EVENT: "):
                    logger.info("[eval-worker stdout] %s", line)
                    continue
                try:
                    evt = json.loads(line[7:])
                except Exception:
                    logger.debug("[eval-worker] non-JSON event line: %s", line)
                    continue
                et = evt.get("event")
                if et == "benchmark_started":
                    name = evt.get("benchmark")
                    prev = self.current_benchmark
                    self.current_benchmark = name
                    for entry in self.current_benchmarks:
                        if entry.get("name") == name:
                            entry["status"] = "running"
                            break
                    else:
                        self.current_benchmarks.append({"name": name, "status": "running"})
                    if name and name != prev:
                        self._log_event(
                            "benchmark_started",
                            f"Benchmark {name} on {short}",
                            benchmark=name,
                            model=model,
                            experiment_index=idx,
                        )
                elif et == "benchmark_complete":
                    name = evt.get("benchmark")
                    score = float(evt.get("score") or 0.0)
                    stderr_val = float(evt.get("stderr") or 0.0)
                    for entry in self.current_benchmarks:
                        if entry.get("name") == name:
                            entry["status"] = "error" if score == 0.0 else "done"
                            entry["score"] = score
                            entry["stderr"] = stderr_val
                            break
                    self._log_event(
                        "benchmark_complete",
                        f"Benchmark {name} on {short} = {score:.3f}",
                        benchmark=name,
                        model=model,
                        experiment_index=idx,
                        score=score,
                        stderr=stderr_val,
                    )
                elif et in ("worker_started", "model_loaded", "worker_complete", "worker_error"):
                    logger.info("[eval-worker] %s: %s", et, evt)
                else:
                    logger.debug("[eval-worker] unknown event: %s", evt)

        async def _consume_stderr() -> None:
            assert proc.stderr is not None
            while True:
                line_bytes = await proc.stderr.readline()
                if not line_bytes:
                    return
                line = line_bytes.decode(errors="replace").rstrip()
                if line:
                    logger.info("[eval-worker stderr] %s", line)

        try:
            await asyncio.gather(
                _consume_stdout(),
                _consume_stderr(),
                proc.wait(),
            )
        except asyncio.CancelledError:
            await self._terminate_eval_subprocess()
            raise
        finally:
            self._eval_subprocess = None

        rc = proc.returncode
        duration = time.perf_counter() - t0

        if rc not in (0, 3):
            try:
                os.unlink(output_path)
            except OSError:
                pass
            raise RuntimeError(f"eval-worker exited with code {rc}")

        try:
            with open(output_path) as f:
                result = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"eval-worker output unreadable: {exc}") from exc
        finally:
            try:
                os.unlink(output_path)
            except OSError:
                pass

        scores = dict(result.get("scores") or {})
        stderrs = dict(result.get("stderrs") or {})
        avg = sum(scores.values()) / len(scores) if scores else 0.0
        return {
            "scores": scores,
            "stderrs": stderrs,
            "avg_score": float(avg),
            "duration": float(result.get("duration_seconds") or duration),
            "method": "baseline",
            "run_id": run_id,
        }

    async def _terminate_eval_subprocess(self) -> None:
        """SIGTERM with a 5s grace, then SIGKILL — guarantees memory reclaim."""
        proc = self._eval_subprocess
        if proc is None or proc.returncode is not None:
            return
        try:
            proc.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
            return
        except asyncio.TimeoutError:
            logger.warning("[campaign] eval-worker ignored SIGTERM, sending SIGKILL")
        except Exception as exc:  # noqa: BLE001
            logger.debug("[campaign] eval-worker wait error after SIGTERM: %s", exc)
        try:
            proc.kill()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[campaign] eval-worker did not exit after SIGKILL: %s", exc)

    async def _run_single_experiment(self, exp: dict, db, idx: int) -> dict:
        method = exp.get("method") or ("eval_only" if exp.get("eval_only") else "sequential")
        model = exp.get("model") or exp.get("base_model") or "meta-llama/Llama-3.2-3B-Instruct"

        if exp.get("eval_only"):
            return await self._run_eval_subprocess(exp, model, idx)

        if method == "ept":
            # Use the same start_runner() entry point /api/ept/start uses so
            # that /api/ept/status, /population, /history, and the EPT page
            # all see the run while it's in flight. Constructing EPTRunner
            # directly bypasses attach_runner() and leaves the dashboard blind.
            from agents.ept.runner import get_runner, start_runner

            cfg = {
                "base_model": model,
                "population_size": int(exp.get("population_size", 4)),
                "max_generations": int(exp.get("max_generations", 5)),
                "mutation_steps": int(exp.get("mutation_steps", 100)),
                "crossover_strategy": exp.get("crossover", "uniform"),
            }
            for k, v in exp.items():
                if k not in ("model", "base_model", "method", "name", "crossover",
                             "population_size", "max_generations", "mutation_steps"):
                    cfg[k] = v
            t0 = time.perf_counter()
            ept = start_runner(cfg)

            # Poll the singleton until it finishes. Cancel on stop.
            deadline = time.monotonic() + _EXPERIMENT_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if not ept.status.get("is_running"):
                    break
                if self.status == "stopping":
                    try:
                        ept.request_stop()
                    except Exception:
                        pass
                    # Give it a few seconds to wind down gracefully.
                    for _ in range(10):
                        if not ept.status.get("is_running"):
                            break
                        await asyncio.sleep(1)
                    break
                while self.status == "paused":
                    await asyncio.sleep(2)
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            if ept.status.get("is_running"):
                try:
                    ept.request_stop()
                except Exception:
                    pass
                raise TimeoutError(
                    f"EPT experiment timed out after {_EXPERIMENT_TIMEOUT_SECONDS}s"
                )

            err = ept.status.get("error")
            if err:
                raise RuntimeError(f"EPT runner reported error: {err}")

            champion = None
            try:
                # Read champion from the same singleton other endpoints see.
                live = get_runner() or ept
                champion = live.manager.get_champion()  # type: ignore[attr-defined]
            except Exception:
                champion = None
            scores: dict[str, float] = {}
            avg = 0.0
            champion_id: str | None = None
            if champion is not None:
                # PopulationManager returns either a Member object with attrs
                # or a dict; handle both gracefully.
                if hasattr(champion, "scores"):
                    scores = dict(getattr(champion, "scores", {}) or {})
                    avg = float(getattr(champion, "avg_score", 0.0) or 0.0)
                    champion_id = getattr(champion, "member_id", None)
                elif isinstance(champion, dict):
                    scores = dict(champion.get("scores") or {})
                    avg = float(champion.get("avg_score") or 0.0)
                    champion_id = champion.get("member_id")
            return {
                "scores": scores,
                "avg_score": float(avg),
                "duration": float(time.perf_counter() - t0),
                "method": "ept",
                "champion_id": champion_id,
                "run_id": ept.status.get("run_id"),
            }

        # Default — sequential evolution.
        from agents.runner import _TASKS, start_evolution

        run_id = f"camp-{uuid.uuid4().hex[:8]}"
        config = {
            "base_model": model,
            "max_generations": int(exp.get("max_generations", 5)),
            "max_samples": int(exp.get("max_samples", 1000)),
            "lora_rank": int(exp.get("lora_rank", 16)),
            "learning_rate": float(exp.get("learning_rate", 2e-4)),
            "batch_size": int(exp.get("batch_size", 2)),
        }
        if exp.get("target_benchmarks"):
            config["target_benchmarks"] = exp["target_benchmarks"]

        if db is None:
            raise RuntimeError("campaign runner requires a LineageDB instance")
        # Persist a "starting" run row so the regular dashboards see it.
        try:
            await db.save_run(run_id, "starting", config)
        except Exception as exc:
            logger.warning("[campaign] save_run(%s) failed: %s", run_id, exc)

        task = start_evolution(run_id=run_id, config=config, db=db)

        # Wait for the task to finish (or timeout).
        deadline = time.monotonic() + _EXPERIMENT_TIMEOUT_SECONDS
        t0 = time.perf_counter()
        while time.monotonic() < deadline:
            if task.done():
                break
            if self.status == "stopping":
                from agents.runner import request_stop  # type: ignore
                try:
                    request_stop(run_id)
                except Exception:
                    pass
                break
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        if not task.done():
            # Force-cancel if the deadline expired.
            task.cancel()
            await asyncio.sleep(1.0)
            raise TimeoutError(
                f"experiment timed out after {_EXPERIMENT_TIMEOUT_SECONDS}s"
            )
        if task.exception():
            raise task.exception()

        # Read final scores from the DB.
        scores: dict[str, float] = {}
        avg = 0.0
        try:
            gens = await db.get_all_generations(run_id=run_id)
            if gens:
                last = gens[-1]
                cs = last.get("child_scores") or {}
                if isinstance(cs, str):
                    try:
                        cs = json.loads(cs)
                    except Exception:
                        cs = {}
                scores = {k: float(v) for k, v in (cs or {}).items()
                          if isinstance(v, (int, float))}
                avg = sum(scores.values()) / len(scores) if scores else 0.0
        except Exception as exc:
            logger.warning("[campaign] read final scores for %s failed: %s", run_id, exc)

        return {
            "scores": scores,
            "avg_score": float(avg),
            "duration": float(time.perf_counter() - t0),
            "method": "sequential",
            "run_id": run_id,
        }

    async def _db_upsert_result(self, db, idx: int, exp: dict, *, status: str, started: bool) -> None:
        if not db or not getattr(db, "_pool", None) or not self.active_plan_id:
            return
        # When `started=True` (each new experiment attempt) we want a fresh
        # row: refresh started_at to NOW() AND clear any leftover finish-side
        # columns (completed_at, scores, duration, error) so a re-run of the
        # same (plan_id, experiment_index) doesn't render stale data from a
        # prior attempt. The previous COALESCE-on-started_at preserved the
        # first-ever timestamp forever, which made the UI show times hours
        # off from reality after a force-stop + restart.
        async with db._pool.acquire() as conn:
            if started:
                await conn.execute(
                    """
                    INSERT INTO campaign_results
                        (plan_id, experiment_index, config, status, started_at,
                         completed_at, scores, duration_seconds, error)
                    VALUES ($1, $2, $3::jsonb, $4, NOW(),
                            NULL, '{}'::jsonb, 0, NULL)
                    ON CONFLICT (plan_id, experiment_index) DO UPDATE SET
                        status = EXCLUDED.status,
                        config = EXCLUDED.config,
                        started_at = NOW(),
                        completed_at = NULL,
                        scores = '{}'::jsonb,
                        duration_seconds = 0,
                        error = NULL
                    """,
                    self.active_plan_id, idx, json.dumps(exp), status,
                )
            else:
                # Status-only update (rare path) — keep the existing started_at.
                await conn.execute(
                    """
                    INSERT INTO campaign_results
                        (plan_id, experiment_index, config, status, started_at)
                    VALUES ($1, $2, $3::jsonb, $4, NOW())
                    ON CONFLICT (plan_id, experiment_index) DO UPDATE SET
                        status = EXCLUDED.status,
                        config = EXCLUDED.config
                    """,
                    self.active_plan_id, idx, json.dumps(exp), status,
                )

    async def _db_finish_result(
        self, db, idx: int, *, status: str,
        scores: dict | None = None, duration: float = 0.0, error: str | None = None,
    ) -> None:
        if not db or not getattr(db, "_pool", None) or not self.active_plan_id:
            return
        async with db._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE campaign_results
                SET status = $1, scores = $2::jsonb, duration_seconds = $3,
                    error = $4, completed_at = NOW()
                WHERE plan_id = $5 AND experiment_index = $6
                """,
                status, json.dumps(scores or {}), float(duration or 0.0),
                error, self.active_plan_id, idx,
            )

    async def _cleanup_gpu(self) -> None:
        try:
            import gc
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
            except Exception:
                pass
            # Log DRAM headroom between experiments so a slow leak across the
            # campaign is visible in logs rather than only when the host wedges.
            try:
                from utils.memory_guard import check_memory
                check_memory(min_gb=0.0, label="campaign-between-experiments")
            except Exception:
                pass
        except Exception:
            pass

    async def _notify(self, message: str, emoji: str = "🔔") -> None:
        try:
            from services.automation_engine import get_engine
            eng = get_engine()
            if eng is not None:
                await eng.notify(message, emoji=emoji, event_type="campaign")
        except Exception as exc:
            logger.debug("[campaign] slack notify failed: %s", exc)


# Module-level singleton (matches services.automation_engine pattern).
_RUNNER = CampaignRunner()


def get_campaign_runner() -> CampaignRunner:
    return _RUNNER
