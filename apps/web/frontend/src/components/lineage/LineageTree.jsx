import { useRef, useState, useEffect, useMemo, useCallback } from 'react';
import { C, F } from '../../config/colors';
import LineageNode from './LineageNode';

const W = 120;
const H = 110;
const COLS = 5;
const PAD = 70;

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
  return sorted.map((node, i) => {
    const col = i % COLS;
    const row = Math.floor(i / COLS);
    return {
      ...node,
      x: PAD + col * W,
      y: PAD + row * H,
    };
  });
}

function bounds(layoutNodes) {
  if (!layoutNodes.length) return { minX: 0, minY: 0, vbW: 400, vbH: 300 };
  const xs = layoutNodes.map(n => n.x);
  const ys = layoutNodes.map(n => n.y);
  const minX = Math.min(...xs) - PAD;
  const maxX = Math.max(...xs) + PAD;
  const minY = Math.min(...ys) - PAD;
  const maxY = Math.max(...ys) + PAD;
  return { minX, minY, vbW: Math.max(320, maxX - minX), vbH: Math.max(280, maxY - minY) };
}

export default function LineageTree({
  nodes: apiNodes,
  edges: apiEdges,
  onNodeClick,
  selectedNode,
}) {
  const svgRef = useRef(null);
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const [dragging, setDragging] = useState(false);
  const [dragStart, setDragStart] = useState(null);

  const { layouted, edgeLines, viewBox, vbWidth, vbHeight } = useMemo(() => {
    const layoutedNodes =
      Array.isArray(apiNodes) && apiNodes.length > 0 ? layoutApiNodes(apiNodes) : [];
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
      lines = layoutedNodes.map((node, i) => {
        if (i === 0) return null;
        const parent = layoutedNodes[i - 1];
        return {
          key: `edge-${i}`,
          x1: parent.x,
          y1: parent.y,
          x2: node.x,
          y2: node.y,
          promoted: node.promoted,
        };
      }).filter(Boolean);
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
