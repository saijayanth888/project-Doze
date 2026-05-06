"""Action registry for the workflow engine.

Each action is a small class with:

* ``kind`` — slug used in workflow JSON (e.g. ``"notify.slack"``)
* ``label`` — human-friendly name shown in the UI
* ``description`` — short doc
* ``schema`` — list of typed fields the UI's form builder uses to render
  a config form. Field shape::

      {"name": "message", "type": "string|number|boolean|select|textarea",
       "label": "...", "required": True/False,
       "default": <any>, "help": "...", "options": [...]   # only for select
      }

* ``async execute(self, *, config, context, engine)`` — runs the action.
  Returns an ``ActionResult`` whose ``output`` becomes part of the run trace
  and feeds ``context["last"]`` for the next action's interpolation.

Templating
----------
String fields support a tiny ``{var.path}`` substitution against ``context``.
For example, ``"GSM8K dropped to {child_scores.gsm8k}"``. Missing vars render
as ``""``. This is intentionally limited — no logic inside templates.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, ClassVar
from uuid import uuid4

import httpx

from config.settings import settings

logger = logging.getLogger("modelforge.automation.actions")


# ── Templating ─────────────────────────────────────────────────────────

_TEMPLATE = re.compile(r"\{([a-zA-Z_][\w.]*)\}")


def _resolve(path: str, ctx: dict[str, Any]) -> Any:
    cur: Any = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def render_template(value: Any, ctx: dict[str, Any]) -> Any:
    """Substitute ``{a.b.c}`` tokens in strings; pass non-strings through."""
    if not isinstance(value, str):
        return value

    def sub(m: re.Match) -> str:
        v = _resolve(m.group(1), ctx)
        if v is None:
            return ""
        if isinstance(v, float):
            return f"{v:.4f}".rstrip("0").rstrip(".")
        return str(v)

    return _TEMPLATE.sub(sub, value)


def render_config(cfg: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Recursively render template strings in a config dict."""
    if isinstance(cfg, dict):
        return {k: render_config(v, ctx) for k, v in cfg.items()}
    if isinstance(cfg, list):
        return [render_config(v, ctx) for v in cfg]
    return render_template(cfg, ctx)


# ── Result envelope ────────────────────────────────────────────────────


@dataclass
class ActionResult:
    status: str = "ok"  # "ok" | "skipped" | "error"
    message: str = ""
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_trace(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "output": self.output,
            "error": self.error,
        }


# ── Action base ────────────────────────────────────────────────────────


class Action:
    kind: ClassVar[str] = ""
    label: ClassVar[str] = ""
    description: ClassVar[str] = ""
    schema: ClassVar[list[dict[str, Any]]] = []

    async def execute(self, *, config: dict[str, Any], context: dict[str, Any], engine: Any) -> ActionResult:
        raise NotImplementedError


# ── Notification actions ───────────────────────────────────────────────


class NotifySlack(Action):
    kind = "notify.slack"
    label = "Send Slack message"
    description = "Post a message to the configured Slack webhook. Honors the global event allow-list."
    schema = [
        {"name": "message", "type": "textarea", "label": "Message", "required": True,
         "help": "Supports {placeholders} from the trigger payload, e.g. {child_scores.gsm8k}."},
        {"name": "emoji", "type": "string", "label": "Emoji", "default": "🤖",
         "help": "Prepended to the message in Slack."},
        {"name": "event_type", "type": "string", "label": "Event type tag", "default": None,
         "help": "Used for the per-event allow-list. Leave blank to always send when configured."},
    ]

    async def execute(self, *, config, context, engine):
        message = str(config.get("message") or "")
        if not message.strip():
            return ActionResult(status="skipped", message="No message to send")
        emoji = str(config.get("emoji") or "🤖")
        event_type = config.get("event_type") or None
        try:
            await engine.notify(message, emoji, event_type=event_type)
            return ActionResult(message=f"Slack notify queued ({event_type or 'no-tag'})",
                                output={"sent": True, "event_type": event_type})
        except Exception as exc:
            return ActionResult(status="error", error=str(exc), message="Slack delivery failed")


class HttpPost(Action):
    kind = "http.post"
    label = "HTTP POST"
    description = "Send a JSON POST to any URL — generic webhook out."
    schema = [
        {"name": "url", "type": "string", "label": "URL", "required": True},
        {"name": "body", "type": "textarea", "label": "JSON body",
         "help": "Supports {placeholders}. Empty body sends {}.",
         "default": "{}"},
        {"name": "timeout_seconds", "type": "number", "label": "Timeout (s)", "default": 10},
    ]

    async def execute(self, *, config, context, engine):
        import json as _json
        url = str(config.get("url") or "").strip()
        if not url:
            return ActionResult(status="error", error="url required", message="No URL configured")
        try:
            payload = config.get("body") or "{}"
            if isinstance(payload, str):
                payload = _json.loads(payload) if payload.strip() else {}
        except _json.JSONDecodeError as exc:
            return ActionResult(status="error", error=str(exc), message="Body is not valid JSON")
        timeout = float(config.get("timeout_seconds") or 10)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload)
            return ActionResult(
                status="ok" if resp.status_code < 400 else "error",
                message=f"POST {url} → HTTP {resp.status_code}",
                output={"status_code": resp.status_code, "body": resp.text[:500]},
                error=None if resp.status_code < 400 else f"HTTP {resp.status_code}",
            )
        except Exception as exc:
            return ActionResult(status="error", error=str(exc), message=f"POST {url} failed")


# ── Control-plane actions ──────────────────────────────────────────────


class EvolutionStart(Action):
    kind = "evolution.start"
    label = "Start evolution run"
    description = "Kick off an evolution run with the given config. Skips if a run is already active."
    schema = [
        {"name": "base_model", "type": "string", "label": "Base model",
         "default": "meta-llama/Llama-3.2-3B-Instruct"},
        {"name": "max_generations", "type": "number", "label": "Generations", "default": 2},
        {"name": "max_samples", "type": "number", "label": "Max training samples", "default": 1000},
        {"name": "lora_rank", "type": "number", "label": "LoRA rank", "default": 16},
        {"name": "batch_size", "type": "number", "label": "Batch size", "default": 2},
        {"name": "learning_rate", "type": "number", "label": "Learning rate", "default": 0.0002},
    ]

    async def execute(self, *, config, context, engine):
        from agents import start_evolution  # late import — avoids circular

        # Skip if a run is already active.
        try:
            row = await engine.db.get_dashboard_run()
            if row and row.get("status") in ("running", "starting"):
                return ActionResult(
                    status="skipped",
                    message=f"Run {row.get('run_id')} already active",
                )
        except Exception:
            pass

        run_id = f"run-{uuid4().hex[:8]}"
        run_config = {k: v for k, v in config.items() if v is not None}
        try:
            await engine.db.save_run(run_id, "starting", run_config)
            start_evolution(run_id, run_config, engine.db)
        except Exception as exc:
            return ActionResult(status="error", error=str(exc), message="Failed to start evolution")
        return ActionResult(
            message=f"Evolution started — run {run_id}",
            output={"run_id": run_id, "config": run_config},
        )


class EptStart(Action):
    kind = "ept.start"
    label = "Start EPT (population) run"
    description = "Kick off a population-based evolution run."
    schema = [
        {"name": "population_size", "type": "number", "label": "Population size", "default": 4},
        {"name": "max_generations", "type": "number", "label": "Generations", "default": 2},
        {"name": "base_model", "type": "string", "label": "Base model",
         "default": "TinyLlama/TinyLlama-1.1B-Chat-v1.0"},
        {"name": "target_benchmarks", "type": "textarea", "label": "Target benchmarks (CSV)",
         "default": "arc_challenge,hellaswag"},
        {"name": "eval_benchmarks", "type": "textarea", "label": "Eval benchmarks (CSV)",
         "default": "arc_challenge,hellaswag,mmlu"},
        {"name": "mutation_steps", "type": "number", "label": "Mutation steps", "default": 30},
        {"name": "mutation_samples", "type": "number", "label": "Mutation samples", "default": 100},
    ]

    async def execute(self, *, config, context, engine):
        try:
            from agents.ept.runner import start_ept
        except Exception as exc:
            return ActionResult(status="error", error=str(exc), message="EPT module unavailable")

        def _csv(s):
            if isinstance(s, list):
                return s
            return [t.strip() for t in str(s or "").split(",") if t.strip()]

        cfg = {
            "population_size": int(config.get("population_size") or 4),
            "max_generations": int(config.get("max_generations") or 2),
            "base_model": config.get("base_model"),
            "target_benchmarks": _csv(config.get("target_benchmarks")),
            "eval_benchmarks": _csv(config.get("eval_benchmarks")),
            "mutation_steps": int(config.get("mutation_steps") or 30),
            "mutation_samples": int(config.get("mutation_samples") or 100),
        }
        try:
            run_id = start_ept(cfg, engine.db)
        except Exception as exc:
            return ActionResult(status="error", error=str(exc), message="Failed to start EPT run")
        return ActionResult(
            message=f"EPT started — run {run_id}",
            output={"run_id": run_id, "config": cfg},
        )


class ChampionRollback(Action):
    kind = "champion.rollback"
    label = "Rollback champion to a generation"
    description = "Promote a specific past adapter back to champion."
    schema = [
        {"name": "adapter_id", "type": "string", "label": "Adapter id",
         "help": "Format: <run_id>__gen<N>", "required": True},
    ]

    async def execute(self, *, config, context, engine):
        adapter_id = str(config.get("adapter_id") or "").strip()
        if not adapter_id or "__gen" not in adapter_id:
            return ActionResult(status="error", error="invalid adapter_id",
                                message="adapter_id must look like 'run-xxx__gen1'")
        try:
            from services.model_registry import ModelRegistry
            run_id, gen_part = adapter_id.split("__gen", 1)
            generation = int(gen_part)
            gen_row = None
            try:
                gens = await engine.db.get_all_generations()
                for g in gens or []:
                    if str(g.get("run_id")) == run_id and int(g.get("generation") or 0) == generation:
                        gen_row = g
                        break
            except Exception:
                pass
            if not gen_row:
                return ActionResult(status="error", error="not found",
                                    message=f"No generation row for {adapter_id}")
            scores = gen_row.get("child_scores") or {}
            avg = sum(scores.values()) / len(scores) if scores else 0.0
            adapter_path = (Path(settings.resolve_data_root()) / "adapters" / run_id / f"gen-{generation}").as_posix()
            ModelRegistry().set_champion({
                "name": f"mf-{run_id}-g{generation}",
                "base_model": "unknown",
                "generation": generation,
                "adapter_path": adapter_path,
                "adapter_id": adapter_id,
                "scores": scores,
                "avg_score": round(avg, 4),
                "promoted_at": datetime.now(timezone.utc).isoformat(),
            })
            return ActionResult(message=f"Rolled back to {adapter_id}",
                                output={"adapter_id": adapter_id, "avg_score": avg})
        except Exception as exc:
            return ActionResult(status="error", error=str(exc), message="Rollback failed")


class CleanupAdapters(Action):
    kind = "cleanup.adapters"
    label = "Cleanup discarded adapters"
    description = "Delete adapter dirs older than N days that aren't in the promoted lineage."
    schema = [
        {"name": "keep_days", "type": "number", "label": "Keep days", "default": 7},
    ]

    async def execute(self, *, config, context, engine):
        keep_days = int(config.get("keep_days") or 7)
        try:
            data_root = settings.resolve_data_root()
            adapters_dir = Path(data_root) / "adapters"
            if not adapters_dir.is_dir():
                return ActionResult(status="skipped", message="No adapters directory")
            promoted: set[str] = set()
            try:
                for g in await engine.db.get_all_generations() or []:
                    if g.get("promoted") or g.get("is_champion"):
                        rid = str(g.get("run_id") or "")
                        if rid:
                            promoted.add(f"{rid}__gen{int(g.get('generation') or 0)}")
            except Exception:
                pass
            cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
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
                    if aid in promoted:
                        continue
                    mtime = datetime.fromtimestamp(gen_dir.stat().st_mtime, tz=timezone.utc)
                    if mtime > cutoff:
                        continue
                    size = sum(f.stat().st_size for f in gen_dir.rglob("*") if f.is_file())
                    freed_mb += size / (1024 * 1024)
                    shutil.rmtree(gen_dir, ignore_errors=True)
                    deleted += 1
            return ActionResult(
                message=f"Cleaned {deleted} adapters, freed {freed_mb:.0f}MB"
                        if deleted else "Nothing to clean",
                output={"deleted": deleted, "freed_mb": round(freed_mb, 1)},
            )
        except Exception as exc:
            return ActionResult(status="error", error=str(exc), message="Cleanup failed")


# ── Diagnostic / inspection actions ────────────────────────────────────


class DriftCheck(Action):
    kind = "drift.check"
    label = "Detect benchmark drift"
    description = "Compare the latest two generation score sets and flag drops over threshold."
    schema = [
        {"name": "threshold_pct", "type": "number", "label": "Drop threshold (%)", "default": 5.0,
         "help": "A benchmark must drop by more than this to count as drift."},
    ]

    async def execute(self, *, config, context, engine):
        threshold_pct = float(config.get("threshold_pct") or 5.0)
        try:
            gens = await engine.db.get_all_generations(include_archived=False)
        except Exception as exc:
            return ActionResult(status="error", error=str(exc), message="Could not read generations")
        scores = []
        for g in sorted(gens or [], key=lambda r: int(r.get("generation") or 0)):
            cs = g.get("child_scores") or {}
            # Some DAO call paths return JSONB as a raw string; normalize.
            if isinstance(cs, str):
                import json as _json
                try:
                    cs = _json.loads(cs)
                except Exception:
                    cs = {}
            if isinstance(cs, dict) and cs:
                scores.append({k: float(v) for k, v in cs.items() if isinstance(v, (int, float))})
        if len(scores) < 2:
            return ActionResult(status="skipped", message="Need ≥2 generations",
                                output={"drifts": []})
        latest, previous = scores[-1], scores[-2]
        drifts: list[dict[str, Any]] = []
        for bench, new_v in latest.items():
            old_v = previous.get(bench)
            if old_v is None:
                continue
            delta_pct = (float(new_v) - float(old_v)) * 100
            if delta_pct < -threshold_pct:
                drifts.append({"benchmark": bench, "delta_pct": round(delta_pct, 2),
                               "previous": old_v, "current": new_v})
        return ActionResult(
            message=(f"Drift detected on {len(drifts)} benchmark(s)" if drifts else "No drift"),
            output={"drifts": drifts, "threshold_pct": threshold_pct},
        )


class HealthCheck(Action):
    kind = "health.check"
    label = "Service health check"
    description = "Ping postgres, redis, and ollama. Returns per-service status."
    schema = []

    async def execute(self, *, config, context, engine):
        from config.redis_pool import get_redis
        results = {"postgres": "unknown", "redis": "unknown", "ollama": "unknown"}
        try:
            results["postgres"] = "ok" if await engine.db.ping() else "down"
        except Exception:
            results["postgres"] = "down"
        try:
            r = await get_redis()
            await r.ping()
            results["redis"] = "ok"
        except Exception:
            results["redis"] = "down"
        try:
            host = settings.ollama_host.rstrip("/")
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{host}/api/tags")
                results["ollama"] = "ok" if resp.status_code == 200 else "down"
        except Exception:
            results["ollama"] = "down"
        failed = [k for k, v in results.items() if v != "ok"]
        return ActionResult(
            status="ok" if not failed else "error",
            message=("All services healthy" if not failed else f"Degraded: {', '.join(failed)}"),
            output={"services": results, "failed": failed},
        )


class Wait(Action):
    kind = "wait"
    label = "Wait"
    description = "Sleep for N seconds. Useful for sequencing."
    schema = [
        {"name": "seconds", "type": "number", "label": "Seconds", "default": 5},
    ]

    async def execute(self, *, config, context, engine):
        seconds = max(0.0, float(config.get("seconds") or 0))
        await asyncio.sleep(seconds)
        return ActionResult(message=f"Waited {seconds}s", output={"seconds": seconds})


# ── Registry ───────────────────────────────────────────────────────────

_ALL_ACTIONS: list[type[Action]] = [
    NotifySlack,
    HttpPost,
    EvolutionStart,
    EptStart,
    ChampionRollback,
    CleanupAdapters,
    DriftCheck,
    HealthCheck,
    Wait,
]

ACTION_REGISTRY: dict[str, type[Action]] = {a.kind: a for a in _ALL_ACTIONS}


def action_schemas() -> list[dict[str, Any]]:
    """All actions exposed to the UI form builder."""
    out = []
    for cls in _ALL_ACTIONS:
        out.append({
            "kind": cls.kind,
            "label": cls.label,
            "description": cls.description,
            "schema": cls.schema,
        })
    return out


__all__ = [
    "ACTION_REGISTRY",
    "Action",
    "ActionResult",
    "action_schemas",
    "render_config",
    "render_template",
]
