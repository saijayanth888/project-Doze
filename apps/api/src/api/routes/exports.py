"""Paper-ready export endpoints.

Returns:
  - GET /api/export/evolution-curves   PNG/SVG of score trends
  - GET /api/export/lineage-tree       PNG/SVG of the full lineage
  - GET /api/export/ablation-table     LaTeX-formatted table
  - GET /api/export/experiment-data    Complete JSON dump

Charts use matplotlib (added to requirements). The lineage tree falls back to
a hand-rolled SVG when matplotlib + networkx aren't both available — keeps the
lineage export usable with one fewer dep.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response, StreamingResponse

from api.deps import get_db
from services import experiment_tracker
from services.lineage_db import LineageDB

logger = logging.getLogger("modelforge.routes.exports")
router = APIRouter()

BENCH_ORDER = ["mmlu", "arc_challenge", "hellaswag", "gsm8k", "humaneval"]
BENCH_COLORS_HEX = {
    "mmlu":          "#76b900",
    "arc_challenge": "#a78bfa",
    "hellaswag":     "#2dd4bf",
    "gsm8k":         "#fb923c",
    "humaneval":     "#e879f9",
}


def _matplotlib():
    """Lazy import — matplotlib is heavy and optional until next image rebuild."""
    try:
        import matplotlib
        matplotlib.use("Agg")  # headless backend, no display required
        import matplotlib.pyplot as plt
        return plt
    except Exception as exc:  # pragma: no cover
        raise HTTPException(
            status_code=503,
            detail=(
                f"matplotlib unavailable: {exc}. Add matplotlib to apps/api/requirements.txt "
                "(already done) and rebuild the API image."
            ),
        )


def _fmt_response(buf: io.BytesIO, fmt: str, base_name: str) -> Response:
    fmt = (fmt or "png").lower()
    if fmt not in ("png", "svg"):
        raise HTTPException(status_code=400, detail="format must be 'png' or 'svg'")
    media = "image/png" if fmt == "png" else "image/svg+xml"
    return Response(
        content=buf.getvalue(),
        media_type=media,
        headers={"Content-Disposition": f'inline; filename="{base_name}.{fmt}"'},
    )


# ── Evolution curves ─────────────────────────────────────────────────────


@router.get("/evolution-curves")
async def evolution_curves(
    format: str = Query("png", pattern="^(png|svg)$"),
    width: float = 9.0,
    height: float = 5.0,
    db: LineageDB = Depends(get_db),
) -> Response:
    """Per-benchmark score lines vs generation, plus the average as a thicker
    accent line. One champion's lineage at a time (the latest run with ≥1 row)."""
    plt = _matplotlib()
    runs = await db.list_runs(include_archived=False, limit=200)
    if not runs:
        raise HTTPException(status_code=404, detail="No runs to plot.")
    target = next((r for r in runs if r.get("status") in ("completed", "running")), runs[0])
    gens = await db.get_all_generations(run_id=target["run_id"])
    gens = sorted(gens or [], key=lambda r: int(r.get("generation") or 0))
    if not gens:
        raise HTTPException(status_code=404, detail=f"No generations for run {target['run_id']}.")

    series: dict[str, list[tuple[int, float]]] = {b: [] for b in BENCH_ORDER}
    stderr_series: dict[str, list[tuple[int, float]]] = {b: [] for b in BENCH_ORDER}
    avg_pts: list[tuple[int, float]] = []
    for g in gens:
        cs = g.get("child_scores") or {}
        if isinstance(cs, str):
            try:
                cs = json.loads(cs)
            except Exception:
                cs = {}
        if not isinstance(cs, dict):
            continue
        gn = int(g.get("generation") or 0)
        # Extract stderrs from the generation's data blob.
        se_raw = g.get("data") or {}
        if isinstance(se_raw, str):
            try:
                se_raw = json.loads(se_raw)
            except Exception:
                se_raw = {}
        se = (se_raw.get("stderrs") or {}) if isinstance(se_raw, dict) else {}
        vals = []
        for b in BENCH_ORDER:
            v = cs.get(b)
            if isinstance(v, (int, float)):
                series[b].append((gn, float(v)))
                vals.append(float(v))
            stderr_series[b].append((gn, float(se[b]) if b in se and isinstance(se[b], (int, float)) else 0.0))
        if vals:
            avg_pts.append((gn, sum(vals) / len(vals)))

    fig, ax = plt.subplots(figsize=(float(width), float(height)), dpi=150)
    fig.patch.set_facecolor("#0a0e16")
    ax.set_facecolor("#0a0e16")
    for b in BENCH_ORDER:
        pts = series[b]
        if not pts:
            continue
        xs, ys = zip(*pts)
        ax.plot(
            xs, ys, marker="o", linewidth=1.4, markersize=5,
            color=BENCH_COLORS_HEX[b], label=b,
        )
        se_pts = stderr_series.get(b) or []
        if se_pts and len(se_pts) == len(pts):
            _xs, ses = zip(*se_pts)
            lower = [y - s for y, s in zip(ys, ses)]
            upper = [y + s for y, s in zip(ys, ses)]
            ax.fill_between(xs, lower, upper, color=BENCH_COLORS_HEX[b], alpha=0.15, linewidth=0)
    if avg_pts:
        xs, ys = zip(*avg_pts)
        ax.plot(xs, ys, color="#76b900", linewidth=2.4, marker="D",
                markersize=7, label="avg", zorder=10)
    ax.set_xlabel("generation", color="#94a3b8")
    ax.set_ylabel("score", color="#94a3b8")
    ax.set_title(
        f"Evolution curves — {target.get('base_model') or target['run_id']}",
        color="#e2e8f0", fontsize=12,
    )
    ax.tick_params(colors="#94a3b8")
    for spine in ax.spines.values():
        spine.set_color("#1e293b")
    ax.grid(True, color="#1e293b", linewidth=0.5)
    ax.legend(loc="best", frameon=False, labelcolor="#cbd5e1", fontsize=9)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format=format, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return _fmt_response(buf, format, "evolution-curves")


# ── Lineage tree ─────────────────────────────────────────────────────────


def _svg_lineage_tree(tree: dict[str, Any]) -> str:
    """Hand-rolled SVG fallback so the lineage export works without graphviz.

    Lays out one column per generation, siblings stacked vertically,
    parent→child edges drawn with arrow-style line. Same conventions as the
    LineageTree React component.
    """
    nodes = list(tree.get("nodes") or [])
    if not nodes:
        return (
            "<?xml version='1.0' encoding='UTF-8'?>\n"
            "<svg xmlns='http://www.w3.org/2000/svg' width='400' height='80'>"
            "<text x='12' y='40' fill='#94a3b8' font-family='monospace' font-size='12'>"
            "No lineage data yet.</text></svg>"
        )

    # Bucket by generation.
    by_gen: dict[int, list[dict]] = {}
    for n in nodes:
        g = int(n.get("generation") or 0)
        by_gen.setdefault(g, []).append(n)
    gens = sorted(by_gen.keys())

    col_w, row_h = 260, 100
    pad_x, pad_y = 50, 50
    width = pad_x * 2 + (len(gens) - 1) * col_w + 220
    height_rows = max(len(siblings) for siblings in by_gen.values())
    height = pad_y * 2 + max(220, (height_rows - 1) * row_h + 80)

    pos: dict[str, tuple[int, int]] = {}
    parts: list[str] = []
    parts.append(
        f"<?xml version='1.0' encoding='UTF-8'?>"
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
        f"style='background:#0a0e16'>"
    )
    parts.append(
        "<defs><marker id='a' viewBox='0 0 10 10' refX='9' refY='5' "
        "markerWidth='6' markerHeight='6' orient='auto'>"
        "<path d='M0,0 L10,5 L0,10 z' fill='#475569'/></marker></defs>"
    )

    # First pass: positions.
    for gi, g in enumerate(gens):
        siblings = by_gen[g]
        for si, n in enumerate(siblings):
            x = pad_x + gi * col_w
            y = pad_y + si * row_h + 40
            pos[str(n.get("id"))] = (x, y)

    # Second pass: edges (parent_id → this).
    by_id = {str(n.get("id")): n for n in nodes}
    for n in nodes:
        pid = n.get("parent_id")
        if not pid or pid not in by_id:
            continue
        x1, y1 = pos[str(pid)]
        x2, y2 = pos[str(n.get("id"))]
        promoted = bool(n.get("promoted"))
        stroke = "#76b900" if promoted else "#475569"
        parts.append(
            f"<line x1='{x1+18}' y1='{y1}' x2='{x2-18}' y2='{y2}' "
            f"stroke='{stroke}' stroke-width='1.5' stroke-dasharray='6 3' marker-end='url(#a)'/>"
        )

    # Third pass: nodes.
    for n in nodes:
        x, y = pos[str(n.get("id"))]
        promoted = bool(n.get("promoted"))
        is_champ = bool(n.get("is_champion"))
        fill = "rgba(212,165,116,0.15)" if is_champ else ("rgba(118,185,0,0.12)" if promoted else "rgba(239,68,68,0.08)")
        stroke = "#d4a574" if is_champ else ("#76b900" if promoted else "#ef4444")
        parts.append(
            f"<g transform='translate({x},{y})'>"
            f"<circle r='20' fill='{fill}' stroke='{stroke}' stroke-width='2'/>"
            f"<text y='4' text-anchor='middle' font-family='JetBrains Mono, monospace' "
            f"font-size='11' font-weight='700' fill='{stroke}'>G{int(n.get('generation') or 0)}</text>"
            f"<text y='38' text-anchor='middle' font-family='JetBrains Mono, monospace' "
            f"font-size='9' fill='#94a3b8'>{float(n.get('avg_score') or 0):.3f}</text>"
            f"</g>"
        )

    parts.append("</svg>")
    return "".join(parts)


@router.get("/lineage-tree")
async def lineage_tree_export(
    format: str = Query("svg", pattern="^(png|svg)$"),
    db: LineageDB = Depends(get_db),
) -> Response:
    # Reuse the same builder the API's /api/lineage/tree route uses by importing it.
    from api.routes.lineage import _build_lineage_tree
    gens = await db.get_all_generations()
    tree = _build_lineage_tree(gens or []).model_dump()

    if format == "svg":
        svg = _svg_lineage_tree(tree)
        return Response(
            content=svg,
            media_type="image/svg+xml",
            headers={"Content-Disposition": 'inline; filename="lineage-tree.svg"'},
        )

    # PNG path: rasterise the SVG via matplotlib + xml — simpler is to draw
    # directly with matplotlib instead.
    plt = _matplotlib()
    fig, ax = plt.subplots(figsize=(10, 6), dpi=150)
    fig.patch.set_facecolor("#0a0e16")
    ax.set_facecolor("#0a0e16")
    ax.axis("off")
    nodes = tree.get("nodes") or []
    if not nodes:
        ax.text(0.5, 0.5, "No lineage data yet.", color="#94a3b8",
                ha="center", va="center", fontfamily="monospace")
    else:
        # Bucket by gen.
        by_gen: dict[int, list[dict]] = {}
        for n in nodes:
            by_gen.setdefault(int(n.get("generation") or 0), []).append(n)
        gens = sorted(by_gen.keys())
        pos: dict[str, tuple[float, float]] = {}
        for gi, g in enumerate(gens):
            for si, n in enumerate(by_gen[g]):
                pos[str(n.get("id"))] = (gi, -si)
        # Edges
        by_id = {str(n.get("id")): n for n in nodes}
        for n in nodes:
            pid = n.get("parent_id")
            if pid and pid in by_id:
                x1, y1 = pos[str(pid)]
                x2, y2 = pos[str(n.get("id"))]
                ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                            arrowprops=dict(arrowstyle="->", color="#475569", lw=1.4))
        for n in nodes:
            x, y = pos[str(n.get("id"))]
            color = "#d4a574" if n.get("is_champion") else ("#76b900" if n.get("promoted") else "#ef4444")
            ax.scatter([x], [y], s=600, c=color, alpha=0.18, edgecolors=color, linewidths=2)
            ax.text(x, y, f"G{int(n.get('generation') or 0)}", color=color,
                    ha="center", va="center", fontweight="bold", fontfamily="monospace", fontsize=10)
            ax.text(x, y - 0.35, f"{float(n.get('avg_score') or 0):.3f}",
                    color="#94a3b8", ha="center", va="center", fontfamily="monospace", fontsize=8)
        ax.set_xlim(-0.5, max(0, max(gens)) + 0.5)
        ax.set_ylim(-max(1, max(len(v) for v in by_gen.values())), 1)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return _fmt_response(buf, format, "lineage-tree")


# ── LaTeX ablation table ─────────────────────────────────────────────────


def _build_latex_table(records: list[dict[str, Any]]) -> str:
    """One row per (run, generation), columns = key benchmarks + decision.

    Caption + label included so this can be pasted straight into a LaTeX
    document without manual fixup. Uses booktabs.
    """
    benches = BENCH_ORDER
    lines = [
        r"% Auto-generated by ModelForge — paste the booktabs preamble:",
        r"%   \usepackage{booktabs}",
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{ModelForge evolution results — per-generation benchmark scores"
        r" with promotion decisions.}",
        r"\label{tab:modelforge-evolution}",
        r"\begin{tabular}{lll" + "r" * len(benches) + "rl}",
        r"\toprule",
        " & ".join([
            r"Run", r"Gen", r"Base",
            *[fr"\textsc{{{b.replace('_', r'\_')}}}" for b in benches],
            r"Avg",
            r"Decision",
        ]) + r" \\",
        r"\midrule",
    ]
    for rec in records:
        scores = (rec.get("eval_results") or {}).get("per_benchmark_scores") or {}
        avg = (
            sum(float(scores[b]) for b in benches if isinstance(scores.get(b), (int, float)))
            / max(1, sum(1 for b in benches if isinstance(scores.get(b), (int, float))))
        ) if scores else 0.0
        decision = (rec.get("eval_results") or {}).get("decision") or "?"
        line = " & ".join([
            r"\texttt{" + str(rec.get("run_id") or "")[:14].replace("_", r"\_") + "}",
            str(rec.get("generation") or ""),
            r"\texttt{" + str(rec.get("base_model") or "")[:18].replace("_", r"\_") + "}",
            *[
                f"{float(scores[b]):.3f}" if isinstance(scores.get(b), (int, float)) else "--"
                for b in benches
            ],
            f"{avg:.3f}",
            decision,
        ]) + r" \\"
        lines.append(line)
    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ])
    return "\n".join(lines) + "\n"


@router.get("/ablation-table", response_class=PlainTextResponse)
async def ablation_table(
    limit: int = 200,
    db: LineageDB = Depends(get_db),
) -> PlainTextResponse:
    records = await experiment_tracker.build_records(db, limit=int(limit))
    return PlainTextResponse(
        content=_build_latex_table(records),
        media_type="text/x-tex",
        headers={"Content-Disposition": 'attachment; filename="modelforge_ablation.tex"'},
    )


# ── Complete JSON dump ───────────────────────────────────────────────────


@router.get("/experiment-data")
async def experiment_data(
    limit: int = 1000,
    db: LineageDB = Depends(get_db),
) -> StreamingResponse:
    records = await experiment_tracker.build_records(db, limit=int(limit))
    payload = {
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "tool": "ModelForge",
        "record_count": len(records),
        "records": records,
    }
    body = json.dumps(payload, default=str, indent=2)
    return StreamingResponse(
        iter([body]),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="modelforge_experiment_data.json"'},
    )
