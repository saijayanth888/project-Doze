"""Lineage tree and activity feed routes."""

import logging
from typing import Any

from fastapi import APIRouter, Depends

from api.deps import get_db
from api.schemas.lineage import LineageEdge, LineageNodeSchema, LineageTree
from services.lineage_db import LineageDB
from services.mock_data import mock_activity_feed, mock_lineage_tree

logger = logging.getLogger("modelforge.routes.lineage")

router = APIRouter()


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
        scores: dict = gen.get("scores", gen.get("child_scores", {}))
        avg_score = sum(scores.values()) / len(scores) if scores else 0.0
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


@router.get("/tree", response_model=LineageTree)
async def get_lineage_tree(
    db: LineageDB = Depends(get_db),
) -> LineageTree:
    """Return the full lineage tree (nodes + edges).

    Falls back to mock data when the DB is unavailable or empty.
    """
    try:
        generations = await db.get_all_generations()
    except Exception as exc:
        logger.warning("DB unavailable for lineage tree, using mock: %s", exc)
        generations = []

    if not generations:
        mock = mock_lineage_tree()
        nodes = [LineageNodeSchema(**n) for n in mock["nodes"]]
        edges = [LineageEdge(**e) for e in mock["edges"]]
        return LineageTree(
            nodes=nodes,
            edges=edges,
            total_nodes=mock["total_nodes"],
            total_promoted=mock["total_promoted"],
            total_discarded=mock["total_discarded"],
            champion_id=mock["champion_id"],
        )

    return _build_lineage_tree(generations)


@router.get("/activity", response_model=list[dict[str, Any]])
async def get_activity_feed(
    db: LineageDB = Depends(get_db),
) -> list[dict]:
    """Return the 8 most recent evolution events."""
    try:
        generations = await db.get_all_generations()
    except Exception as exc:
        logger.warning("DB unavailable for activity feed, using mock: %s", exc)
        generations = []

    if not generations:
        return mock_activity_feed()

    # Build a synthetic activity feed from generation rows
    events: list[dict] = []
    generations_sorted = sorted(generations, key=lambda g: g.get("generation", 0))

    for gen in generations_sorted:
        gen_num = gen.get("generation", 0)
        run_id = gen.get("run_id", "unknown")
        promoted = bool(gen.get("promoted", False))
        created_at = gen.get("created_at") or gen.get("timestamp")

        events.append(
            {
                "id": f"evt-gen-{gen_num}",
                "type": "generation_complete"
                if not promoted
                else "champion_promoted"
                if gen.get("is_champion")
                else "generation_complete",
                "message": (
                    f"Generation {gen_num} promoted to champion"
                    if promoted and gen.get("is_champion")
                    else f"Generation {gen_num} {'promoted' if promoted else 'discarded'}"
                ),
                "generation": gen_num,
                "run_id": run_id,
                "timestamp": str(created_at) if created_at else None,
            }
        )

    # Return newest-first, limited to 8
    events.reverse()
    return events[:8]
