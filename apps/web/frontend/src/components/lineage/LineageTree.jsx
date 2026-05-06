import { useRef, useState, useEffect, useMemo, useCallback } from 'react';
import { C, F } from '../../config/colors';
import LineageNode from './LineageNode';

// Generation-based layout: each generation is its own column flowing left → right,
// siblings within a generation stack vertically and stay centered around y=0.
// Without this, a single champion node was rendering tucked into a corner of a
// fixed-aspect viewBox and the canvas felt empty.
const COL_W = 240;   // horizontal distance between consecutive generations
const ROW_H = 140;   // vertical distance between siblings of the same generation
const PAD_X = 160;   // horizontal breathing room added to the viewBox
const PAD_Y = 140;   // vertical breathing room added to the viewBox

function normalizeApiNode(n) {
  const scores = n.scores || n.childScores || {};
  return {
    ...n,
    scores,
    childScores: scores,
    isChampion: Boolean(n.is_champion ?? n.isChampion),
    decisionReason: n.decision_reason ?? n.decisionReason ?? '',
    parentId: n.parent_id ?? n.parentId ?? null,
  };
}

function layoutApiNodes(apiNodes) {
  const sorted = [...apiNodes].map(normalizeApiNode).sort((a, b) => a.generation - b.generation);
  const byGen = new Map();
  for (const n of sorted) {
    const g = Number(n.generation ?? 0);
    if (!byGen.has(g)) byGen.set(g, []);
    byGen.get(g).push(n);
  }
  const gens = [...byGen.keys()].sort((a, b) => a - b);
  const minGen = gens[0] ?? 0;
  const out = [];
  for (const g of gens) {
    const siblings = byGen.get(g);
    siblings.forEach((node, i) => {
      const yOffset = (i - (siblings.length - 1) / 2) * ROW_H;
      out.push({
        ...node,
        x: (g - minGen) * COL_W,
        y: yOffset,
      });
    });
  }
  return out;
}

function bounds(layoutNodes) {
  if (!layoutNodes.length) return { minX: 0, minY: 0, vbW: 800, vbH: 480 };
  const xs = layoutNodes.map(n => n.x);
  const ys = layoutNodes.map(n => n.y);
  const minX = Math.min(...xs) - PAD_X;
  const maxX = Math.max(...xs) + PAD_X;
  const minY = Math.min(...ys) - PAD_Y;
  const maxY = Math.max(...ys) + PAD_Y;
  // Maintain a wide aspect ratio so a single node still fills the canvas instead
  // of leaving most of the available pane empty.
  const vbW = Math.max(800, maxX - minX);
  const vbH = Math.max(480, maxY - minY);
  return { minX, minY, vbW, vbH };
}

export default function LineageTree({
  nodes: apiNodes,
  edges: apiEdges,
  onNodeClick,
  selectedNode,
  baseModel,           // optional: synthesizes a "Gen 0 · base" root node so the
                        // tree always has 2+ nodes connected by an edge.
}) {
  const svgRef = useRef(null);
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const [dragging, setDragging] = useState(false);
  const [dragStart, setDragStart] = useState(null);

  const { layouted, edgeLines, viewBox, vbWidth, vbHeight } = useMemo(() => {
    // Inject a synthetic Gen 0 representing the unmodified base model. This
    // gives the tree a real "ancestor → descendant" shape on first generation
    // and clarifies what every later checkpoint forked off of. The synthetic
    // node carries `synthetic: true` so click handlers can avoid trying to
    // open it as a real adapter.
    const realNodes = Array.isArray(apiNodes) ? apiNodes : [];
    const minRealGen = realNodes.length
      ? Math.min(...realNodes.map((n) => Number(n.generation ?? 1)))
      : 1;
    const augmented =
      baseModel && realNodes.length && minRealGen >= 1
        ? [
            {
              id: '__base__',
              label: `Base · ${baseModel}`,
              generation: 0,
              promoted: false,
              scores: {},
              avg_score: null,
              is_champion: false,
              parent_id: null,
              method: 'base',
              decision_reason: 'Untrained base model — origin of all lineage in this run.',
              synthetic: true,
            },
            ...realNodes,
          ]
        : realNodes;

    const layoutedNodes =
      augmented.length > 0 ? layoutApiNodes(augmented) : [];
    const byId = Object.fromEntries(layoutedNodes.map((n) => [n.id, n]));

    let lines = [];
    if (layoutedNodes.length && Array.isArray(apiEdges) && apiEdges.length) {
      lines = apiEdges
        .map((e) => {
          const s = byId[e.source];
          const t = byId[e.target];
          if (!s || !t) return null;
          return { key: `${e.source}-${e.target}`, x1: s.x, y1: s.y, x2: t.x, y2: t.y, promoted: e.promoted };
        })
        .filter(Boolean);
    } else if (layoutedNodes.length > 1) {
      // Prefer real parent links when the API didn't provide explicit edges;
      // fall back to "previous-generation chain" so even a flat list still draws
      // something meaningful instead of an arbitrary linear chain.
      lines = layoutedNodes
        .map((node) => {
          const parent = node.parentId ? byId[node.parentId] : null;
          if (parent) {
            return {
              key: `${parent.id}-${node.id}`,
              x1: parent.x,
              y1: parent.y,
              x2: node.x,
              y2: node.y,
              promoted: node.promoted,
            };
          }
          // Fallback: connect to nearest earlier generation so the chain still draws.
          const earlier = layoutedNodes.filter((n) => n.generation < node.generation);
          if (!earlier.length) return null;
          const closest = earlier.reduce((best, n) =>
            n.generation > (best?.generation ?? -Infinity) ? n : best
          , null);
          if (!closest) return null;
          return {
            key: `${closest.id || closest.generation}-${node.id || node.generation}`,
            x1: closest.x,
            y1: closest.y,
            x2: node.x,
            y2: node.y,
            promoted: node.promoted,
          };
        })
        .filter(Boolean);
    }

    const b = bounds(layoutedNodes);
    const viewBoxStr = `${b.minX} ${b.minY} ${b.vbW} ${b.vbH}`;
    return { layouted: layoutedNodes, edgeLines: lines, viewBox: viewBoxStr, vbWidth: b.vbW, vbHeight: b.vbH };
  }, [apiNodes, apiEdges]);

  const handleWheel = useCallback((e) => {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 0.9 : 1.1;
    setTransform(t => ({ ...t, scale: Math.min(3, Math.max(0.35, t.scale * factor)) }));
  }, []);

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    el.addEventListener('wheel', handleWheel, { passive: false });
    return () => el.removeEventListener('wheel', handleWheel);
  }, [handleWheel]);

  function handleMouseDown(e) {
    if (e.button !== 0) return;
    setDragging(true);
    setDragStart({ clientX: e.clientX, clientY: e.clientY, tx: transform.x, ty: transform.y });
  }

  function handleMouseMove(e) {
    if (!dragging || !dragStart || !svgRef.current) return;
    const svg = svgRef.current;
    const rect = svg.getBoundingClientRect();
    const scaleX = vbWidth / Math.max(rect.width, 1);
    const scaleY = vbHeight / Math.max(rect.height, 1);
    const dx = (e.clientX - dragStart.clientX) * scaleX;
    const dy = (e.clientY - dragStart.clientY) * scaleY;
    setTransform(t => ({ ...t, x: dragStart.tx + dx, y: dragStart.ty + dy }));
  }

  function handleMouseUp() {
    setDragging(false);
    setDragStart(null);
  }

  const resetView = () => setTransform({ x: 0, y: 0, scale: 1 });

  if (Array.isArray(apiNodes) && apiNodes.length === 0) {
    return (
      <div
        style={{
          position: 'relative',
          width: '100%',
          height: '100%',
          minHeight: 400,
          borderRadius: 8,
          border: '1px solid #1e293b',
          background: '#06080d',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 24,
        }}
      >
        <p style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM, textAlign: 'center', maxWidth: 440, margin: 0, lineHeight: 1.55 }}>
          No lineage in the database yet. After evolution runs complete with Postgres connected, nodes and edges appear here. If you expect data,
          confirm the API uses the same database volume as your stack (Settings → Test Connections).
        </p>
      </div>
    );
  }

  return (
    <div
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        minHeight: 400,
        borderRadius: 8,
        border: '1px solid #1e293b',
        background: '#06080d',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%) rotate(-30deg)',
          fontFamily: 'Instrument Serif, Georgia, serif',
          fontSize: 64,
          color: 'rgba(129,140,248,0.04)',
          letterSpacing: 8,
          pointerEvents: 'none',
          userSelect: 'none',
          zIndex: 1,
          whiteSpace: 'nowrap',
        }}
      >
        MODELFORGE™
      </div>

      <svg
        ref={svgRef}
        width="100%"
        height="100%"
        viewBox={viewBox}
        preserveAspectRatio="xMidYMid meet"
        style={{ cursor: dragging ? 'grabbing' : 'grab', display: 'block' }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.scale})`}>
          {edgeLines.map((ln) => (
            <line
              key={ln.key}
              x1={ln.x1}
              y1={ln.y1}
              x2={ln.x2}
              y2={ln.y2}
              stroke={ln.promoted ? '#1e4d1a' : '#1e293b'}
              strokeWidth={ln.promoted ? 1.5 : 1}
              strokeDasharray="6 3"
              vectorEffect="non-scaling-stroke"
              style={{
                animation: 'edge-flow 2s linear infinite',
              }}
            />
          ))}

          {layouted.map((node) => (
            <g key={node.id || node.generation} transform={`translate(${node.x},${node.y})`}>
              <LineageNode
                node={node}
                onClick={onNodeClick}
                isSelected={selectedNode && (selectedNode.id === node.id || selectedNode.generation === node.generation)}
              />
            </g>
          ))}
        </g>
      </svg>

      <div
        style={{
          position: 'absolute',
          bottom: 16,
          right: selectedNode ? 340 : 16,
          display: 'flex',
          gap: 8,
          transition: 'right 300ms ease',
          zIndex: 5,
        }}
      >
        {[
          { label: '+', fn: () => setTransform(t => ({ ...t, scale: Math.min(3, t.scale * 1.2) })) },
          { label: '−', fn: () => setTransform(t => ({ ...t, scale: Math.max(0.35, t.scale / 1.2) })) },
          { label: '⌂', fn: resetView },
        ].map(btn => (
          <button
            key={btn.label}
            type="button"
            onClick={btn.fn}
            style={{
              width: 32,
              height: 32,
              background: '#0c1018',
              border: '1px solid #1e293b',
              borderRadius: 6,
              color: '#64748b',
              cursor: 'pointer',
              fontSize: 14,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            {btn.label}
          </button>
        ))}
      </div>
    </div>
  );
}
