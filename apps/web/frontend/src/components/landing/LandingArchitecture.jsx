import { useState } from 'react';
import { C, F } from '../../config/colors';

const ARCH = [
  { id: 'react', label: 'React Dashboard', sub: ':3000', color: '#38bdf8', desc: 'Model Lineage Tree · Training Monitor · Eval Comparisons', x: '50%', y: '5%', w: 220 },
  { id: 'api', label: 'FastAPI Backend', sub: ':8000', color: C.acc, desc: 'REST + WebSocket · /evolve /models /lineage /evaluate', x: '50%', y: '27%', w: 210 },
  { id: 'langgraph', label: 'LangGraph Agent', sub: 'Evolution', color: '#c084fc', desc: 'Evaluate → Identify → Curate → Train → Compare → Decide', x: '22%', y: '54%', w: 200 },
  { id: 'n8n', label: 'n8n Workflows', sub: ':5678', color: C.warning, desc: 'Scheduling · Triggers · Notifications · Webhooks', x: '50%', y: '54%', w: 180 },
  { id: 'postgres', label: 'PostgreSQL + pgvector', sub: 'lineage DB', color: C.ind, desc: 'Generations · Champions · Embeddings · Training dedup', x: '79%', y: '54%', w: 210 },
  { id: 'ollama', label: 'Ollama', sub: ':11434', color: C.success, desc: 'Dev inference · Self-analysis · Fast local serving', x: '24%', y: '80%', w: 155 },
  { id: 'vllm', label: 'vLLM', sub: ':8001', color: C.acc, desc: 'Batched eval · High-throughput benchmark runs', x: '53%', y: '80%', w: 150 },
  { id: 'wandb', label: 'W&B', sub: 'tracking', color: '#f472b6', desc: 'Experiment tracking · Training metrics · Run history', x: '80%', y: '80%', w: 130 },
];

const LINE_SEGMENTS = [
  ['50%', '12%', '50%', '27%'],
  ['50%', '36%', '22%', '54%'],
  ['50%', '36%', '50%', '54%'],
  ['50%', '36%', '79%', '54%'],
  ['22%', '63%', '24%', '80%'],
  ['22%', '63%', '53%', '80%'],
  ['79%', '63%', '80%', '80%'],
];

export default function LandingArchitecture() {
  const [hov, setHov] = useState(null);

  return (
    <section id="architecture" style={{ background: C.bg, borderTop: `1px solid ${C.border}`, padding: '80px 0' }}>
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '0 24px' }}>
        <div style={{ textAlign: 'center', marginBottom: 44 }}>
          <div style={{ fontFamily: F.mono, fontSize: 11, color: C.ind, letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10 }}>System Architecture</div>
          <h2 style={{ fontFamily: F.display, fontSize: 'clamp(1.8rem,3.5vw,2.8rem)', fontWeight: 400, color: C.txtP }}>Built for the edge of hardware.</h2>
        </div>
        <div style={{ position: 'relative', height: 370, background: C.bgS, borderRadius: 12, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
          {ARCH.map(comp => (
            <div
              key={comp.id}
              role="presentation"
              onMouseEnter={() => setHov(comp.id)}
              onMouseLeave={() => setHov(null)}
              style={{
                position: 'absolute',
                left: `calc(${comp.x} - ${comp.w / 2}px)`,
                top: comp.y,
                width: comp.w,
                background: hov === comp.id ? C.bgE : C.bgC,
                border: `1px solid ${hov === comp.id ? `${comp.color}55` : C.border}`,
                borderRadius: 7,
                padding: '9px 11px',
                cursor: 'default',
                transition: 'all 200ms',
                boxShadow: hov === comp.id ? `0 0 18px ${comp.color}22` : 'none',
                zIndex: hov === comp.id ? 10 : 1,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: hov === comp.id ? 5 : 0 }}>
                <div style={{ width: 6, height: 6, borderRadius: '50%', background: comp.color, boxShadow: `0 0 5px ${comp.color}80` }} />
                <span style={{ fontFamily: F.ui, fontSize: 12, fontWeight: 600, color: C.txtP }}>{comp.label}</span>
                <span style={{ fontFamily: F.mono, fontSize: 9, color: C.txtM, marginLeft: 'auto' }}>{comp.sub}</span>
              </div>
              {hov === comp.id && (
                <div style={{ fontFamily: F.ui, fontSize: 11, color: C.txtS, lineHeight: 1.5 }}>{comp.desc}</div>
              )}
            </div>
          ))}
          <svg style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }} viewBox="0 0 1100 370" preserveAspectRatio="none">
            {LINE_SEGMENTS.map(([x1p, y1p, x2p, y2p], i) => {
              const x1 = (parseFloat(x1p) / 100) * 1100;
              const y1 = (parseFloat(y1p) / 100) * 370;
              const x2 = (parseFloat(x2p) / 100) * 1100;
              const y2 = (parseFloat(y2p) / 100) * 370;
              return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={C.border} strokeWidth="1" strokeDasharray="4 4" />;
            })}
          </svg>
        </div>
        <div style={{ textAlign: 'center', marginTop: 12, fontFamily: F.mono, fontSize: 10, color: C.txtM }}>
          Hover components for details · All services via Docker Compose
        </div>
      </div>
    </section>
  );
}
