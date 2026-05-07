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
import time
import uuid
from datetime import datetime, timezone
from typing import Any

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


class CampaignRunner:
    def __init__(self) -> None:
        self.active_plan_id: str | None = None
        self.status: str = "idle"  # idle | ensuring | running | paused | stopping
        self.current_experiment_index: int = 0
        self.results: list[dict[str, Any]] = []
        self._task: asyncio.Task | None = None
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
            **extra,
        }
        self.events.append(evt)
        if len(self.events) > 100:
            self.events = self.events[-100:]

    # ── Public lifecycle ────────────────────────────────────────

    async def start(self, plan_id: str, experiments: list[dict], db) -> dict:
        if self.status in ("running", "ensuring"):
            raise ValueError("a campaign is already running")
        self.active_plan_id = plan_id
        # Mark "ensuring" so the UI shows the pre-flight phase before any
        # experiment kicks off; the runner flips to "running" once downloads
        # complete.
        self.status = "ensuring"
        self.current_experiment_index = 0
        self.results = []
        self.ensure_progress = []
        self.events = []
        self._event_seq = 0
        self._experiments = list(experiments)
        self._log_event(
            "campaign_started",
            f"Campaign {plan_id} started · {len(experiments)} experiment(s)",
            total_experiments=len(experiments),
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

    def get_status(self) -> dict:
        completed = sum(1 for r in self.results if "completed" in (r.get("status") or ""))
        failed = sum(1 for r in self.results if (r.get("status") or "") == "failed")
        total = len(self._experiments) or 0
        elapsed = (
            time.time() - self.current_started_at
            if self.current_started_at is not None
            else None
        )
        return {
            "status": self.status,
            "plan_id": self.active_plan_id,
            "current_experiment": self.current_experiment_index,
            "total_experiments": total,
            "completed": completed,
            "failed": failed,
            "results": self.results,
            "ensure_progress": list(self.ensure_progress),
            "current_model": self.current_model,
            "current_benchmark": self.current_benchmark,
            "current_method": self.current_method,
            "current_elapsed_seconds": elapsed,
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

            self.current_experiment_index = idx
            model = exp.get("model") or exp.get("base_model") or ""
            method = exp.get("method") or ("eval_only" if exp.get("eval_only") else "sequential")

            # Reset live-progress hints at each experiment boundary so the
            # dashboard reflects the new model immediately, not the old one.
            self.current_model = model
            self.current_method = method
            self.current_benchmark = None
            self.current_started_at = time.time()

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
                self._log_event(
                    "experiment_complete",
                    f"Experiment {idx + 1}/{total} complete · avg={avg:.3f}",
                    experiment_index=idx,
                    model=model,
                    avg_score=float(avg),
                    scores=result.get("scores", {}),
                    duration=result.get("duration", 0.0),
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
        self.status = "idle"
        self.current_model = None
        self.current_benchmark = None
        self.current_method = None
        self.current_started_at = None
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
        )
        await self._notify(
            f"Campaign complete · {completed}/{total} succeeded · {failed} failed",
            "🏁",
        )

    async def _run_single_experiment(self, exp: dict, db, idx: int) -> dict:
        method = exp.get("method") or ("eval_only" if exp.get("eval_only") else "sequential")
        model = exp.get("model") or exp.get("base_model") or "meta-llama/Llama-3.2-3B-Instruct"

        if exp.get("eval_only"):
            from agents.eval_backend import LMEvalHarnessBackend

            run_id = f"baseline-{uuid.uuid4().hex[:8]}"
            backend = LMEvalHarnessBackend()
            t0 = time.perf_counter()
            def _set_bench(name: str) -> None:
                # bench_callback fires from a worker thread (lm-eval is sync).
                # Setting attrs is safe; logging an event is just a list append.
                prev = self.current_benchmark
                self.current_benchmark = name
                if name and name != prev:
                    short = (model or "").split("/")[-1] or model or "?"
                    self._log_event(
                        "benchmark_started",
                        f"Benchmark {name} on {short}",
                        benchmark=name,
                        model=model,
                        experiment_index=idx,
                    )

            result = await backend.evaluate(
                run_id=run_id,
                generation=0,
                adapter_path=None,
                config={"base_model": model, **{k: v for k, v in exp.items()
                        if k in ("eval_limit", "limit")}},
                should_stop=lambda: self.status == "stopping",
                bench_callback=_set_bench,
            )
            scores = dict(result.scores or {})
            avg = sum(scores.values()) / len(scores) if scores else 0.0
            return {
                "scores": scores,
                "avg_score": float(avg),
                "duration": float(result.duration_seconds or (time.perf_counter() - t0)),
                "method": "baseline",
                "run_id": run_id,
            }

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
        async with db._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO campaign_results
                    (plan_id, experiment_index, config, status, started_at)
                VALUES ($1, $2, $3::jsonb, $4, NOW())
                ON CONFLICT (plan_id, experiment_index) DO UPDATE SET
                    status = EXCLUDED.status,
                    started_at = COALESCE(campaign_results.started_at, EXCLUDED.started_at),
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
