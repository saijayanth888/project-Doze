"""WebSocket endpoints for real-time evolution status and activity feed."""

import asyncio
import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from services.lineage_db import LineageDB
from services.mock_data import mock_activity_feed

logger = logging.getLogger("modelforge.routes.websocket")

router = APIRouter()

# Terminal run statuses — no point polling further once reached
_TERMINAL_STATUSES = {"completed", "failed", "stopped"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def _get_db() -> LineageDB:
    """Obtain a LineageDB instance without the FastAPI Depends machinery."""
    try:
        from config.database import get_pool

        pool = await get_pool()
        return LineageDB(pool=pool)
    except Exception as exc:
        logger.debug("WebSocket: DB pool unavailable, returning pool-less LineageDB: %s", exc)
        return LineageDB(pool=None)


@router.websocket("/ws/evolution/{run_id}")
async def ws_evolution(websocket: WebSocket, run_id: str) -> None:
    """Stream evolution run status updates to the client every 2 seconds.

    Closes automatically when the run reaches a terminal state or the client
    disconnects.
    """
    await websocket.accept()
    logger.info("WS /ws/evolution/%s: client connected", run_id)

    db = await _get_db()

    try:
        while True:
            payload: dict

            try:
                run = await db.get_run(run_id)
            except Exception as exc:
                logger.warning("WS evolution %s: DB error: %s", run_id, exc)
                run = None

            if run is None:
                payload = {
                    "run_id": run_id,
                    "status": "not_found",
                    "timestamp": _now_iso(),
                    "error": f"Run '{run_id}' not found",
                }
                await websocket.send_text(json.dumps(payload))
                break

            config = run.get("config") or {}
            if isinstance(config, str):
                try:
                    config = json.loads(config)
                except Exception:
                    config = {}

            status = run.get("status", "unknown")

            payload = {
                "run_id": run_id,
                "status": status,
                "generation": run.get("current_generation", 0),
                "current_step": run.get("current_step"),
                "error": run.get("error"),
                "timestamp": _now_iso(),
            }

            await websocket.send_text(json.dumps(payload))

            if status in _TERMINAL_STATUSES:
                logger.info("WS evolution %s: run is terminal (%s), closing", run_id, status)
                break

            await asyncio.sleep(2)

    except WebSocketDisconnect:
        logger.info("WS /ws/evolution/%s: client disconnected", run_id)
    except Exception as exc:
        logger.error("WS /ws/evolution/%s: unexpected error: %s", run_id, exc)
        try:
            await websocket.send_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "status": "error",
                        "error": str(exc),
                        "timestamp": _now_iso(),
                    }
                )
            )
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/ws/activity")
async def ws_activity(websocket: WebSocket) -> None:
    """Broadcast the latest activity feed to the client every 3 seconds.

    Sends mock data when the database is unavailable, so the frontend always
    has something to display during local development.
    """
    await websocket.accept()
    logger.info("WS /ws/activity: client connected")

    db = await _get_db()

    try:
        while True:
            events: list[dict]

            try:
                generations = await db.get_all_generations()
            except Exception as exc:
                logger.debug("WS activity: DB unavailable, falling back to mock: %s", exc)
                generations = []

            if not generations:
                events = mock_activity_feed()
            else:
                # Build a lightweight synthetic feed from the most recent generations
                events = []
                for gen in sorted(generations, key=lambda g: g.get("generation", 0), reverse=True):
                    gen_num = gen.get("generation", 0)
                    run_id = gen.get("run_id", "unknown")
                    promoted = bool(gen.get("promoted", False))
                    created_at = gen.get("created_at") or gen.get("timestamp")

                    events.append(
                        {
                            "id": f"evt-gen-{gen_num}",
                            "type": "champion_promoted"
                            if promoted and gen.get("is_champion")
                            else "generation_complete",
                            "message": (
                                f"Generation {gen_num} promoted to champion"
                                if promoted and gen.get("is_champion")
                                else f"Generation {gen_num} {'promoted' if promoted else 'discarded'}"
                            ),
                            "generation": gen_num,
                            "run_id": run_id,
                            "timestamp": str(created_at) if created_at else _now_iso(),
                        }
                    )

                events = events[:8]

            payload = {
                "events": events,
                "count": len(events),
                "timestamp": _now_iso(),
            }

            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(3)

    except WebSocketDisconnect:
        logger.info("WS /ws/activity: client disconnected")
    except Exception as exc:
        logger.error("WS /ws/activity: unexpected error: %s", exc)
        try:
            await websocket.send_text(json.dumps({"error": str(exc), "timestamp": _now_iso()}))
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
