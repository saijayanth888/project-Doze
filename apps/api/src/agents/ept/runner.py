"""EPTRunner — drive the full population loop end-to-end.

One global runner so the API surface can poll status/population without
threading the active task through every request. Cancel via ``request_stop``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from .population import PopulationConfig, PopulationManager

logger = logging.getLogger("modelforge.ept.runner")

_RUNNER: "EPTRunner | None" = None
_TASK: asyncio.Task | None = None


def get_runner() -> "EPTRunner | None":
    return _RUNNER


def attach_runner(r: "EPTRunner") -> None:
    global _RUNNER
    _RUNNER = r


class EPTRunner:
    def __init__(self, config: dict[str, Any] | None = None):
        cfg = PopulationConfig.from_dict(config or {})
        self.manager = PopulationManager(cfg)
        self.status: dict[str, Any] = {
            "is_running": False,
            "run_id": self.manager.run_id,
            "generation": 0,
            "max_generations": cfg.max_generations,
            "phase": "idle",
            "champion": None,
            "started_at": None,
            "completed_at": None,
            "error": None,
        }
        self.events: list[dict[str, Any]] = []
        self._cancel = asyncio.Event()

    # ── Public lifecycle ────────────────────────────────────────

    def request_stop(self) -> None:
        self._cancel.set()

    async def run(self) -> None:
        cfg = self.manager.config
        self.status.update({
            "is_running": True,
            "phase": "initializing",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
        })

        async def on_event(ev):
            ev = dict(ev)
            ev["timestamp"] = datetime.now(timezone.utc).isoformat()
            ev["generation"] = self.manager.generation
            self.events.append(ev)
            # Cap to 500 events so a long run doesn't grow without bound.
            if len(self.events) > 500:
                del self.events[: len(self.events) - 500]
            await _slack_notify(ev)

        try:
            await self.manager.initialize_population(on_event=on_event)
            self._update_champion()
            self.status["phase"] = "evolving"

            for gen in range(1, cfg.max_generations + 1):
                if self._cancel.is_set():
                    self.status["phase"] = "stopped"
                    break
                self.status["generation"] = gen
                await self.manager.evolve_generation(on_event=on_event)
                self._update_champion()

            if self.status["phase"] != "stopped":
                self.status["phase"] = "complete"
        except Exception as exc:
            logger.exception("[ept] runner failed")
            self.status["phase"] = "failed"
            self.status["error"] = str(exc)
        finally:
            self.status["is_running"] = False
            self.status["completed_at"] = datetime.now(timezone.utc).isoformat()

    # ── Status helpers ──────────────────────────────────────────

    def _update_champion(self) -> None:
        champ = self.manager.get_champion()
        if not champ:
            return
        self.status["champion"] = {
            "member_id": champ.member_id,
            "generation": champ.generation,
            "avg_score": champ.avg_score,
            "scores": champ.scores,
            "adapter_path": champ.adapter_path,
        }

    # ── External API ────────────────────────────────────────────

    def serialize_population(self) -> dict[str, Any]:
        from dataclasses import asdict
        return {
            "run_id": self.manager.run_id,
            "generation": self.manager.generation,
            "members": [asdict(m) for m in self.manager.population],
        }

    def serialize_history(self) -> dict[str, Any]:
        return {
            "run_id": self.manager.run_id,
            "max_generations": self.manager.config.max_generations,
            "generations": list(self.manager.history),
        }


def start_runner(config: dict[str, Any]) -> "EPTRunner":
    """Start a fresh EPT runner; replaces any previous one. Returns the runner."""
    global _RUNNER, _TASK
    if _RUNNER and _RUNNER.status.get("is_running"):
        raise RuntimeError(f"EPT run {_RUNNER.manager.run_id} is already in progress")
    runner = EPTRunner(config)
    attach_runner(runner)
    _TASK = asyncio.create_task(runner.run())
    return runner


async def _slack_notify(event: dict[str, Any]) -> None:
    """Best-effort: pipe major EPT events into the AutomationEngine's Slack."""
    label = str(event.get("label") or "")
    phase = str(event.get("phase") or "")
    if not label:
        return
    # Only push high-signal events to Slack.
    if phase.startswith("gen") and ("Survival" in label or "===" in label):
        emoji = "🧬"
    elif phase == "init" and ("Initialising" in label or "Seeding" in label):
        emoji = "🌱"
    else:
        return
    try:
        from services.automation import get_engine
        eng = get_engine()
        if eng:
            await eng.notify(label, emoji, event_type="ept")
    except Exception:
        pass
