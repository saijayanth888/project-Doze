import { useRef, useState, useEffect, useCallback } from 'react';
import { GENS, CHAMPION } from '../../config/mockData';
import LineageNode from './LineageNode';
import LineageDetail from './LineageDetail';

const W = 120;
const H = 100;
const COLS = 5;

function layout(gens) {
  return gens.map((g, i) => {
    const col = i % COLS;
    const row = Math.floor(i / COLS);
    return { ...g, x: 60 + col * W, y: 60 + row * H, isChampion: g.generation === CHAMPION?.generation };
  });
}

export default function LineageTree() {
  const svgRef = useRef(null);
  const [selected, setSelected] = useState(null);
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const [dragging, setDragging] = useState(false);
  const [dragStart, setDragStart] = useState(null);
  const nodes = layout(GENS);

  const totalW = COLS * W + 80;
  const totalH = Math.ceil(GENS.length / COLS) * H + 80;

  function handleWheel(e) {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 0.9 : 1.1;
    setTransform(t => ({ ...t, scale: Math.min(3, Math.max(0.3, t.scale * factor)) }));
  }

  function handleMouseDown(e) {
    if (e.button !== 0) return;
    setDragging(true);
    setDragStart({ x: e.clientX - transform.x, y: e.clientY - transform.y });
  }

  function handleMouseMove(e) {
    if (!dragging || !dragStart) return;
    setTransform(t => ({ ...t, x: e.clientX - dragStart.x, y: e.clientY - dragStart.y }));
  }

  function handleMouseUp() { setDragging(false); setDragStart(null); }

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    el.addEventListener('wheel', handleWheel, { passive: false });
    return () => el.removeEventListener('wheel', handleWheel);
  }, []);

  return (
    <div style={{ position: 'relative', height: '100%', overflow: 'hidden' }}>
      {/* WATERMARK */}
      <div style={{
        position: 'absolute',
        top: '50%', left: '50%',
        transform: 'translate(-50%, -50%) rotate(-30deg)',
        fontFamily: 'Instrument Serif',
        fontSize: 64,
        color: 'rgba(129,140,248,0.04)',
        letterSpacing: 8,
        pointerEvents: 'none',
        userSelect: 'none',
        zIndex: 1,
        whiteSpace: 'nowrap',
      }}>
        MODELFORGE™
      </div>

      <svg
        ref={svgRef}
        width="100%"
        height="100%"
        style={{ cursor: dragging ? 'grabbing' : 'grab' }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.scale})`}>
          {/* Edges */}
          {nodes.map((node, i) => {
            if (i === 0) return null;
            const parent = nodes[i - 1];
            return (
              <line
                key={`edge-${i}`}
                x1={parent.x} y1={parent.y}
                x2={node.x} y2={node.y}
                stroke={node.promoted ? '#1e4d1a' : '#1e293b'}
                strokeWidth={node.promoted ? 1.5 : 1}
                strokeDasharray="6 3"
                style={{
                  animation: 'edge-flow 2s linear infinite',
                  animationDelay: `${i * 0.1}s`,
                }}
              />
            );
          })}

          {/* Nodes */}
          {nodes.map(node => (
            <g
              key={node.generation}
              transform={`translate(${node.x},${node.y})`}
              className={node.promoted ? 'animate-node-birth' : 'animate-node-discard'}
              style={{ animationDelay: `${node.generation * 40}ms` }}
            >
              <LineageNode
                node={node}
                onClick={setSelected}
                isSelected={selected?.generation === node.generation}
              />
            </g>
          ))}
        </g>
      </svg>

      {/* Controls */}
      <div style={{
        position: 'absolute',
        bottom: 16,
        right: selected ? 340 : 16,
        display: 'flex',
        gap: 8,
        transition: 'right 300ms ease',
      }}>
        {[
          { label: '+', fn: () => setTransform(t => ({ ...t, scale: Math.min(3, t.scale * 1.2) })) },
          { label: '−', fn: () => setTransform(t => ({ ...t, scale: Math.max(0.3, t.scale / 1.2) })) },
          { label: '⌂', fn: () => setTransform({ x: 0, y: 0, scale: 1 }) },
        ].map(btn => (
          <button
            key={btn.label}
            onClick={btn.fn}
            style={{
              width: 32, height: 32,
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

      {selected && (
        <LineageDetail node={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
