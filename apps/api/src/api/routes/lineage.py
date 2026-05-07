"""Lineage tree and activity feed routes."""

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends

from api.deps import get_db, get_registry
from api.schemas.lineage import LineageEdge, LineageNodeSchema, LineageTree
from api.schemas.models import GenerationInfo
from services.lineage_db import LineageDB
from services.model_registry import ModelRegistry

logger = logging.getLogger("modelforge.routes.lineage")

router = APIRouter()


def _parse_score_dict(val: Any) -> dict[str, float]:
    if val is None:
        return {}
    if isinstance(val, dict):
        out: dict[str, float] = {}
        for k, v in val.items():
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                pass
        return out
    if isinstance(val, str):
        try:
            return _parse_score_dict(json.loads(val))
        except Exception:
            return {}
    return {}


def _row_to_generation_info(row: dict[str, Any]) -> GenerationInfo:
    ts = row.get("created_at")
    created_at: datetime | None = ts if isinstance(ts, datetime) else None
    td = row.get("training_data_size")
    training_data_size = int(td) if td is not None else 0
    dur = row.get("duration_seconds")
    duration_seconds = float(dur) if dur is not None else 0.0
    return GenerationInfo(
        generation=int(row.get("generation", 0)),
        run_id=row.get("run_id"),
        promoted=bool(row.get("promoted", False)),
        parent_scores=_parse_score_dict(row.get("parent_scores")),
        child_scores=_parse_score_dict(row.get("child_scores")),
        decision_reason=row.get("decision_reason"),
        method=row.get("method"),
        training_data_size=training_data_size,
        duration_seconds=duration_seconds,
        created_at=created_at,
    )


def _coerce_score_dict(raw: object) -> dict[str, float]:
    """JSONB columns can come back as already-decoded dicts or as raw JSON strings
    depending on whether asyncpg has the json codec registered. Accept both."""
    import json
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _build_lineage_tree(generations: list[dict]) -> LineageTree:
    """Convert a flat list of generation rows into a LineageTree."""
    nodes: list[LineageNodeSchema] = []
    edges: list[LineageEdge] = []

    # Sort ascending so we process parents before children
    generations_sorted = sorted(generations, key=lambda g: g.get("generation", 0))

    # Track which generation is the most recent promoted one (champion candidate)
    last_promoted_id: str | None = None

    for gen in generations_sorted:
        gen_num: int = gen.get("generation", 0)
        run_id: str = gen.get("run_id", "unknown")
        node_id = f"{run_id}-gen-{gen_num}" if run_id != "unknown" else f"gen-{gen_num}"

        promoted: bool = bool(gen.get("promoted", False))
        scores: dict = _coerce_score_dict(
            gen.get("scores") or gen.get("child_scores") or {}
        )
        score_vals = [v for v in scores.values() if isinstance(v, (int, float))]
        avg_score = sum(score_vals) / len(score_vals) if score_vals else 0.0
        method: str | None = gen.get("method")
        decision_reason: str | None = gen.get("decision_reason")

        node = LineageNodeSchema(
            id=node_id,
            label=f"Generation {gen_num}" + (" ★" if promoted else ""),
            generation=gen_num,
            promoted=promoted,
            scores=scores,
            avg_score=round(avg_score, 4),
            is_champion=False,  # resolved below
            method=method,
            decision_reason=decision_reason,
            parent_id=last_promoted_id if gen_num > 0 else None,
        )
        nodes.append(node)

        if last_promoted_id is not None:
            edges.append(
                LineageEdge(
                    source=last_promoted_id,
                    target=node_id,
                    promoted=promoted,
                )
            )

        if promoted:
            last_promoted_id = node_id

    # Mark the highest-generation promoted node as champion
    promoted_nodes = [n for n in nodes if n.promoted]
    champion_id: str | None = None
    if promoted_nodes:
        champion_node = max(promoted_nodes, key=lambda n: n.generation)
        champion_node.is_champion = True
        champion_id = champion_node.id

    total_promoted = len(promoted_nodes)
    total_discarded = len(nodes) - total_promoted

    return LineageTree(
        nodes=nodes,
        edges=edges,
        total_nodes=len(nodes),
        total_promoted=total_promoted,
        total_discarded=total_discarded,
        champion_id=champion_id,
    )


def _lineage_tree_from_registry_champion(raw: dict | None) -> LineageTree | None:
    """Single-node tree from ``registry.json`` when Postgres has no generation rows.

    Uses the same coercions as ``GET /api/models/champion`` so if the UI shows a champion,
    lineage can still render when the DB has no ``generations`` rows yet.
    """
    if not raw or not isinstance(raw, dict):
        return None

    # Lazy import avoids any circular import at module load.
    from api.routes.models import _normalize_champion_dict

    norm = _normalize_champion_dict(raw)
    base = str(norm.get("base_model") or "").strip()
    ollama_model = str(raw.get("ollama_model") or "").strip()
    adapter_id = str(raw.get("adapter_id") or "").strip()
    adapter_path = str(raw.get("adapter_path") or "").strip()

    if not base:
        if ollama_model:
            base = ollama_model
        elif adapter_id:
            base = f"(adapter {adapter_id})"
        elif adapter_path:
            base = adapter_path
        else:
            return None

    try:
        gen = int(norm.get("generation", 0) or 0)
    except (TypeError, ValueError):
        gen = 0
    scores_in = norm.get("scores")
    scores: dict[str, float] = scores_in if isinstance(scores_in, dict) else {}
    if not scores:
        scores = _parse_score_dict(raw.get("scores"))
    try:
        avg = float(norm.get("avg_score", 0) or 0)
    except (TypeError, ValueError):
        avg = 0.0
    if scores and avg == 0.0:
        avg = sum(scores.values()) / len(scores)

    node_id = adapter_id or (f"registry:{adapter_path}" if adapter_path else f"registry-gen-{gen}")
    method = raw.get("method") or norm.get("method")
    node = LineageNodeSchema(
        id=node_id,
        label=f"Generation {gen} ★" if gen else "Champion (registry) ★",
        generation=max(gen, 0),
        promoted=True,
        scores=scores,
        avg_score=round(avg, 4),
        is_champion=True,
        method=str(method) if method else "registry",
        decision_reason=(
            "Snapshot from model registry — connect Postgres and complete an evolution run "
            "to persist full lineage (runs, edges, and history) in the database."
        ),
        parent_id=None,
    )

    return LineageTree(
        nodes=[node],
        edges=[],
        total_nodes=1,
        total_promoted=1,
        total_discarded=0,
        champion_id=node_id,
    )


@router.get("/generations", response_model=list[GenerationInfo])
async def list_generations(db: LineageDB = Depends(get_db)) -> list[GenerationInfo]:
    """All evolution generations (for dashboards — parent vs child scores)."""
    try:
        if not await db.has_evolution_runs():
            return []
        rows = await db.get_all_generations()
    except Exception as exc:
        logger.warning("DB unavailable for generations list: %s", exc)
        rows = []
    return [_row_to_generation_info(r) for r in rows]


@router.get("/tree", response_model=LineageTree)
async def get_lineage_tree(
    db: LineageDB = Depends(get_db),
    registry: ModelRegistry = Depends(get_registry),
) -> LineageTree:
    """Return the full lineage tree (nodes + edges).

    Primary source is ``generations`` in Postgres. If that table is empty but a champion
    exists on disk (``registry.json``), return a one-node snapshot so the UI is not blank.
    """
    try:
        generations = await db.get_all_generations()
    except Exception as exc:
        logger.warning("DB unavailable for lineage tree: %s", exc)
        generations = []

    if generations:
        return _build_lineage_tree(generations)

    try:
        champ_raw = registry.get_champion()
    except Exception as exc:
        logger.warning("Registry read failed for lineage tree fallback: %s", exc)
        champ_raw = None

    fallback = _lineage_tree_from_registry_champion(
        champ_raw if isinstance(champ_raw, dict) else None
    )
    if fallback is not None:
        return fallback

    return LineageTree(
        nodes=[],
        edges=[],
        total_nodes=0,
        total_promoted=0,
        total_discarded=0,
        champion_id=None,
    )


def _events_from_generations(generations: list[dict]) -> list[dict]:
    events: list[dict] = []
    generations_sorted = sorted(generations, key=lambda g: g.get("generation", 0))
    for gen in generations_sorted:
        gen_num = gen.get("generation", 0)
        run_id = gen.get("run_id", "unknown")
        promoted = bool(gen.get("promoted", False))
        created_at = gen.get("created_at") or gen.get("timestamp")

        msg = (
            f"Generation {gen_num} promoted to champion"
            if promoted and gen.get("is_champion")
            else f"Generation {gen_num} {'promoted' if promoted else 'discarded'}"
        )
        evt_type = (
            "champion_promoted"
            if promoted and gen.get("is_champion")
            else "generation_complete"
        )
        events.append(
            {
                "id": f"evt-gen-{gen_num}",
                "type": evt_type,
                "event": msg,
                "message": msg,
                "generation": gen_num,
                "run_id": run_id,
                "timestamp": str(created_at) if created_at else None,
            }
        )
    events.reverse()
    return events[:8]


async def _fallback_activity_from_run_and_registry(
    db: LineageDB,
    registry: ModelRegistry,
) -> list[dict]:
    """When no generation rows exist yet, still surface latest run + champion so Activity isn't blank."""
    out: list[dict] = []
    try:
        run = await db.get_dashboard_run()
    except Exception as exc:
        logger.warning("activity fallback get_dashboard_run failed: %s", exc)
        run = None

    if isinstance(run, dict) and run.get("run_id"):
        rid = str(run["run_id"])
        st = str(run.get("status", "") or "unknown")
        step = run.get("current_step") or ""
        err = run.get("error")
        parts = [f"Run {rid}", st]
        if step:
            parts.append(f"step: {step}")
        if err:
            parts.append(f"error: {err}")
        msg = " · ".join(parts)
        out.append(
            {
                "id": f"evt-run-{rid}",
                "type": "run_status",
                "event": msg,
                "message": msg,
                "generation": int(run.get("current_generation", 0) or 0),
                "run_id": rid,
                "timestamp": str(run.get("started_at")) if run.get("started_at") else None,
            }
        )

    try:
        champ_raw = registry.get_champion()
    except Exception as exc:
        logger.warning("activity fallback registry read failed: %s", exc)
        champ_raw = None

    if isinstance(champ_raw, dict):
        from api.routes.models import _normalize_champion_dict

        norm = _normalize_champion_dict(champ_raw)
        base = str(norm.get("base_model") or "").strip()
        if not base:
            ollama_model = str(champ_raw.get("ollama_model") or "").strip()
            adapter_id = str(champ_raw.get("adapter_id") or "").strip()
            adapter_path = str(champ_raw.get("adapter_path") or "").strip()
            if ollama_model:
                base = ollama_model
            elif adapter_id:
                base = f"(adapter {adapter_id})"
            elif adapter_path:
                base = adapter_path
        if base:
            try:
                gen = int(norm.get("generation", 0) or 0)
            except (TypeError, ValueError):
                gen = 0
            msg = f"Champion on disk (registry.json): gen {gen} · {base}"
            out.append(
                {
                    "id": "evt-registry-champion",
                    "type": "registry_snapshot",
                    "event": msg,
                    "message": msg,
                    "generation": gen,
                    "run_id": None,
                    "timestamp": str(champ_raw.get("promoted_at")) if champ_raw.get("promoted_at") else None,
                }
            )

    # Run status first (most actionable), then registry champion.
    return out[:8]


def _campaign_events_for_activity_feed() -> list[dict]:
    """In-memory campaign events, shaped to match the activity-feed schema.

    Surfaces every campaign lifecycle moment (start, pre-flight downloads,
    experiment start/complete/fail, per-benchmark transitions, finish) so the
    dashboard's Activity Feed shows live action during a campaign run — the
    eval-only path doesn't write generations rows, so this is the only place
    that data exists.
    """
    try:
        from services.campaign_runner import get_campaign_runner
    except Exception:
        return []
    runner = get_campaign_runner()
    out: list[dict] = []
    for evt in list(runner.events):
        plan_id = evt.get("plan_id")
        out.append({
            "id": evt.get("id"),
            "type": evt.get("type") or "campaign",
            "event": evt.get("message"),
            "message": evt.get("message"),
            "generation": 0,
            "run_id": plan_id,
            "timestamp": evt.get("timestamp"),
        })
    return out


@router.get("/activity", response_model=list[dict[str, Any]])
async def get_activity_feed(
    db: LineageDB = Depends(get_db),
    registry: ModelRegistry = Depends(get_registry),
) -> list[dict]:
    """Return recent activity: generations + campaign events + run/registry fallback."""
    generations: list[dict] = []
    try:
        generations = await db.get_all_generations()
    except Exception as exc:
        logger.warning("DB unavailable for activity feed: %s", exc)
        generations = []

    gen_events = _events_from_generations(generations) if generations else []
    campaign_events = _campaign_events_for_activity_feed()

    merged = gen_events + campaign_events
    if merged:
        merged.sort(key=lambda e: str(e.get("timestamp") or ""), reverse=True)
        return merged[:20]

    return await _fallback_activity_from_run_and_registry(db, registry)
