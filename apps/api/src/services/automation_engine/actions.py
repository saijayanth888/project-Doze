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
import os
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


# ── RAM precheck for evolution.start ──────────────────────────────────
#
# Estimate fp16 base-model memory footprint from the base_model string,
# compare against available RAM, and refuse with an actionable error if
# the math doesn't work. Reused by EvolutionStart.execute() so the
# operator doesn't burn 10+ minutes downloading weights only to get
# SIGKILL'd at 65% of weight-load (the 2026-05-17 OOM pattern).
#
# The parameter-count heuristic is regex-based: match a "<N>B" or
# "<N>b" token in the base_model string. Examples that work:
#   "Qwen/Qwen3-30B-..."          → 30 B
#   "qwen3:30b"                    → 30 B
#   "NousResearch/Hermes-3-Llama-3.1-8B" → 8 B (last match wins → "1" then "8B")
#   "meta-llama/Llama-3.2-3B"      → 3 B
# When no NB token is present we fall back to 8 B (conservative middle-
# ground). The operator can always set MODELFORGE_RAM_PRECHECK=0 to
# skip the check for one-off experiments.

_PARAM_BILLIONS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[Bb](?![a-zA-Z])")


def _estimate_params_billions(base_model: str) -> float:
    """Heuristic parameter-count extraction from a model name string."""
    matches = _PARAM_BILLIONS_RE.findall(base_model or "")
    if not matches:
        return 8.0
    # Pick the LARGEST number — for "Llama-3.1-8B" the "1" and "8" are
    # both candidates; the model size is clearly the 8, not the version.
    return max(float(m) for m in matches)


def _check_ram_for_base_model(base_model: str) -> "ActionResult | None":
    """Return an error ActionResult if free RAM can't host LoRA training
    on the named base. Return None to allow the run."""
    if os.environ.get("MODELFORGE_RAM_PRECHECK", "1") == "0":
        return None
    params_b = _estimate_params_billions(base_model)
    required_gb = (params_b * 2.0) * 1.3 + 10.0
    try:
        import psutil  # type: ignore[import-not-found]
        free_gb = psutil.virtual_memory().available / (1024 ** 3)
    except Exception as exc:
        # If we can't read RAM we can't enforce — log + allow rather than
        # block the entire pipeline on a psutil import failure.
        logger.warning("[ram-precheck] psutil unavailable (%s) — skipping check", exc)
        return None
    if free_gb < required_gb:
        return ActionResult(
            status="error",
            error="insufficient_ram",
            message=(
                f"RAM precheck failed: {free_gb:.1f} GB available, "
                f"need {required_gb:.1f} GB for an estimated {params_b:.0f}B "
                f"parameter base ({base_model!r}). "
                "Rule: free_gb >= params_B * 2 * 1.3 + 10. "
                "Pick a smaller base_model or set MODELFORGE_RAM_PRECHECK=0 "
                "to override (not recommended on this host)."
            ),
            output={
                "base_model": base_model,
                "params_billions": params_b,
                "free_gb": round(free_gb, 1),
                "required_gb": round(required_gb, 1),
            },
        )
    return None


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
        # Track-id pipeline (task #46 path A): when set to e.g.
        # "trading-reflector", the eval-backend dispatch will route to the
        # TradingEvalBackend's per-track scorer instead of the legacy
        # lm-eval-harness path. Empty string = legacy behaviour (preserved).
        {"name": "track_id", "type": "string",
         "label": "Track ID (optional, dispatches per-track eval)",
         "default": ""},
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

        # ── RAM precheck (audit 2026-05-17) ─────────────────────────────
        # The training worker downloads the fp16 base from HuggingFace and
        # loads it into RAM (the GB10 host is unified memory — RAM IS GPU
        # memory). On 2026-05-17 all 5 trading workflows pinned to
        # qwen3:30b OOM-killed the worker (~60 GB fp16 + ~50 GB resident
        # services > 88 GB mf-api cgroup limit). Block bad bases before
        # any HF download burns bandwidth.
        #
        # Formula (per right-sizing analysis 2026-05-17):
        #     required_gb = params_B * 2 * 1.3 + 10
        # The 2 is fp16 bytes/param. The 1.3 is empirical activation +
        # gradient + optimizer overhead for LoRA at batch_size=2. The 10
        # is a fixed framework / staging buffer.
        ram_check = _check_ram_for_base_model(str(config.get("base_model") or ""))
        if ram_check is not None:
            return ram_check

        run_id = f"run-{uuid4().hex[:8]}"
        run_config = {k: v for k, v in config.items() if v is not None}
        # Drop empty-string track_id so the legacy "no track_id" path keeps
        # the key absent from run_config (TradingEvalBackend treats absent
        # and "" identically, but absent is the documented legacy shape --
        # preserve it). Other fields keep "" semantics unchanged.
        if isinstance(run_config.get("track_id"), str) and not run_config["track_id"].strip():
            run_config.pop("track_id", None)
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


class SystemMetrics(Action):
    """Hourly host-vitals snapshot for the phone-readable Slack dashboard.

    Collects CPU%, DRAM, GPU util/VRAM/temp, disk usage at the data root, and
    (optionally) active-campaign progress, then posts a Block-Kit card via
    ``engine.notify_blocks``. The card is intentionally simple — at-a-glance
    on a phone lock screen is the point. Designed to be triggered hourly via
    the seeded "System Metrics Post" workflow, but works fine as an ad-hoc
    debug step too.
    """

    kind = "system.metrics"
    label = "Post system metrics to Slack"
    description = (
        "Snapshot CPU, RAM, GPU, disk, and active-campaign status, then post a "
        "compact Block-Kit card to Slack. Use with a cron trigger for a phone-"
        "readable health feed."
    )
    schema = [
        {"name": "include_gpu", "type": "boolean", "label": "Include GPU stats", "default": True},
        {"name": "include_disk", "type": "boolean", "label": "Include disk usage", "default": True},
        {"name": "include_campaign", "type": "boolean", "label": "Include active campaign",
         "default": True,
         "help": "Show the running campaign's experiment + benchmark progress."},
        {"name": "event_type", "type": "string", "label": "Event tag", "default": "system_metrics",
         "help": "Used for the per-event allow-list. Leave default unless you want to filter."},
    ]

    async def execute(self, *, config, context, engine):
        metrics: dict[str, Any] = {}

        # ── CPU + DRAM via psutil ────────────────────────────────
        try:
            import psutil
            # cpu_percent(interval=None) returns the avg since the last call, so
            # the first call after process boot returns 0.0. A short blocking
            # sample (0.3s) gives a useful reading without holding the loop.
            metrics["cpu_percent"] = float(
                await asyncio.get_running_loop().run_in_executor(
                    None, lambda: psutil.cpu_percent(interval=0.3)
                )
            )
            vm = psutil.virtual_memory()
            metrics["ram_total_gb"] = round(vm.total / 1e9, 2)
            metrics["ram_used_gb"] = round(vm.used / 1e9, 2)
            metrics["ram_avail_gb"] = round(vm.available / 1e9, 2)
            metrics["ram_percent"] = float(vm.percent)
        except Exception as exc:
            logger.warning("[system.metrics] psutil read failed: %s", exc)

        # ── GPU via the same helper /api/system/gpu uses ─────────
        if bool(config.get("include_gpu", True)):
            try:
                from utils.gpu import get_gpu_status
                g = get_gpu_status() or {}
                # Reshape into the dict slack_blocks_health.system_health expects.
                metrics["gpu"] = {
                    "name": g.get("gpu_name"),
                    "vram_total_gb": g.get("vram_total_gb"),
                    "vram_used_gb": g.get("vram_used_gb"),
                    "util_percent": g.get("util_percent"),
                    "temp_celsius": g.get("temp_celsius"),
                    "unified_memory": bool(g.get("unified_memory")),
                }
                # On unified-memory hosts (Spark GB10), surface the unified figures
                # under a sane RAM label too — the card already shows VRAM as
                # "unified mem" and the CPU/RAM row shows the system-RAM picture.
            except Exception as exc:
                logger.warning("[system.metrics] gpu read failed: %s", exc)

        # ── Disk usage at the data root ──────────────────────────
        if bool(config.get("include_disk", True)):
            try:
                root = settings.resolve_data_root()
                du = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: shutil.disk_usage(str(root))
                )
                used = du.total - du.free
                pct = (used / du.total * 100) if du.total else None
                metrics["disk"] = {
                    "data_root": str(root),
                    "total_gb": round(du.total / 1e9, 1),
                    "used_gb": round(used / 1e9, 1),
                    "free_gb": round(du.free / 1e9, 1),
                    "percent": round(pct, 1) if pct is not None else None,
                }
            except Exception as exc:
                logger.warning("[system.metrics] disk read failed: %s", exc)

        # ── Active campaign / dashboard run snapshot ─────────────
        if bool(config.get("include_campaign", True)):
            try:
                from services.campaign_runner import get_campaign_runner
                cr = get_campaign_runner().get_status() or {}
                # Whole-campaign elapsed lives under campaign_elapsed_seconds.
                elapsed_h = None
                ces = cr.get("campaign_elapsed_seconds")
                if isinstance(ces, (int, float)) and ces > 0:
                    elapsed_h = round(float(ces) / 3600.0, 2)
                metrics["campaign"] = {
                    "status": cr.get("status"),
                    "plan_id": cr.get("plan_id"),
                    "name": cr.get("plan_id"),
                    "run_id": cr.get("run_id"),
                    "current_experiment": cr.get("current_experiment"),
                    "total_experiments": cr.get("total_experiments"),
                    "current_model": cr.get("current_model"),
                    "current_benchmark": cr.get("current_benchmark"),
                    "elapsed_h": elapsed_h,
                }
            except Exception as exc:
                logger.warning("[system.metrics] campaign read failed: %s", exc)

        # Hostname so multi-host setups can tell the cards apart.
        try:
            import socket
            metrics["host"] = socket.gethostname()
        except Exception:
            metrics["host"] = "unknown"

        # ── Build + send Block-Kit message ───────────────────────
        try:
            from services.slack_blocks_health import system_health
            text, blocks = system_health(metrics)
        except Exception as exc:
            return ActionResult(status="error", error=str(exc),
                                message="Failed to build system metrics blocks")

        event_type = str(config.get("event_type") or "system_metrics") or None
        try:
            await engine.notify_blocks(text, blocks, event_type=event_type,
                                       log_message=text)
        except Exception as exc:
            return ActionResult(status="error", error=str(exc),
                                message="Slack delivery failed")

        return ActionResult(
            message=f"Posted system metrics ({event_type})",
            output={
                "sent": True,
                "event_type": event_type,
                "cpu_percent": metrics.get("cpu_percent"),
                "ram_percent": metrics.get("ram_percent"),
                "metrics": metrics,
            },
        )


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
    SystemMetrics,
    Wait,
]

ACTION_REGISTRY: dict[str, type[Action]] = {a.kind: a for a in _ALL_ACTIONS}


def register_action(cls: type[Action]) -> type[Action]:
    """Late-binding registration hook for actions defined in other
    packages.

    External action modules (``agents.actions.*``) import ``Action`` /
    ``ActionResult`` from this module. If we tried to import THOSE
    modules back from here at load time we'd create a circular import:
    the registration call would land while the external module is
    still mid-init and the class symbol wouldn't yet be bound.

    The clean fix is to make registration a one-way push from the
    external module *after* it finishes defining its class -- exactly
    what this helper enables. Idempotent: a duplicate ``kind`` is
    rejected with a warning rather than silently overwriting.
    """
    if not getattr(cls, "kind", ""):
        logger.warning("[actions] register_action skipped: class has no kind: %r", cls)
        return cls
    if cls.kind in ACTION_REGISTRY:
        logger.debug("[actions] register_action skipped duplicate kind: %s", cls.kind)
        return cls
    _ALL_ACTIONS.append(cls)
    ACTION_REGISTRY[cls.kind] = cls
    return cls


# Pull in actions defined outside this module. Done as a deferred
# top-level call (not a function) so the import side-effect lands every
# time this module is loaded -- but happens AFTER the base classes
# above are bound, so the external module's ``from ... import Action``
# can succeed. The external module is responsible for calling
# ``register_action(cls)`` at the bottom of its own file.
try:  # pragma: no cover -- the import side-effect IS the test
    from agents.actions import publish_adapter_to_ollama as _publish_module
    _ = _publish_module  # touched so linters don't drop the import
except Exception as exc:  # pragma: no cover -- defensive only
    logger.warning("[actions] failed to load external actions module: %s", exc)

try:  # pragma: no cover -- the import side-effect IS the test
    from agents.actions import publish_adapter_to_hf as _publish_hf_module
    _ = _publish_hf_module  # touched so linters don't drop the import
except Exception as exc:  # pragma: no cover -- defensive only
    logger.warning("[actions] failed to load HF publish action: %s", exc)

try:  # pragma: no cover -- the import side-effect IS the test
    from agents.actions import dataset_build_trading as _build_trading_module
    _ = _build_trading_module  # touched so linters don't drop the import
except Exception as exc:  # pragma: no cover -- defensive only
    logger.warning("[actions] failed to load dataset_build_trading action: %s", exc)


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
