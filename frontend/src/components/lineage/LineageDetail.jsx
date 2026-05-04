import { X } from 'lucide-react';
import { BENCHMARK_LABELS } from '../../config/mockData';
import { BENCH_COLORS } from '../../config/colors';

const KEYS = ['mmlu', 'arc_challenge', 'hellaswag', 'gsm8k', 'humaneval'];

export default function LineageDetail({ node, onClose }) {
  if (!node) return null;

  const avgChild = KEYS.reduce((s, k) => s + node.childScores[k], 0) / KEYS.length;
  const avgParent = KEYS.reduce((s, k) => s + node.parentScores[k], 0) / KEYS.length;

  return (
    <div
      className="animate-slide-right"
      style={{
        position: 'absolute',
        top: 0, right: 0,
        width: 320,
        height: '100%',
        background: '#0c1018',
        borderLeft: '1px solid #1e293b',
        padding: 20,
        overflowY: 'auto',
        zIndex: 20,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 11, color: '#64748b', fontFamily: 'JetBrains Mono', letterSpacing: 2 }}>
            GENERATION
          </div>
          <div style={{ fontFamily: 'Instrument Serif', fontSize: 24, color: '#f1f5f9' }}>
            Gen {node.generation}
          </div>
        </div>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#64748b', padding: 4 }}
        >
          <X size={16} />
        </button>
      </div>

      <div style={{
        display: 'inline-flex',
        padding: '4px 10px',
        borderRadius: 6,
        background: node.promoted ? 'rgba(118,185,0,0.1)' : 'rgba(239,68,68,0.1)',
        border: `1px solid ${node.promoted ? 'rgba(118,185,0,0.3)' : 'rgba(239,68,68,0.3)'}`,
        fontSize: 11,
        fontFamily: 'JetBrains Mono',
        color: node.promoted ? '#76b900' : '#ef4444',
        marginBottom: 16,
      }}>
        {node.promoted ? 'PROMOTED' : 'DISCARDED'}
      </div>

      <div style={{ fontSize: 12, color: '#94a3b8', fontFamily: 'Outfit', marginBottom: 16, lineHeight: 1.5 }}>
        {node.decisionReason}
      </div>

      <div style={{ fontSize: 11, color: '#64748b', fontFamily: 'JetBrains Mono', letterSpacing: 1, marginBottom: 10 }}>
        BENCHMARK SCORES
      </div>

      {KEYS.map(k => {
        const child = node.childScores[k];
        const parent = node.parentScores[k];
        const delta = child - parent;
        return (
          <div key={k} style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ fontSize: 11, fontFamily: 'JetBrains Mono', color: '#64748b' }}>
                {BENCHMARK_LABELS[k]}
              </span>
              <span style={{ fontSize: 11, fontFamily: 'JetBrains Mono', color: BENCH_COLORS[k] }}>
                {(child * 100).toFixed(1)}%
                <span style={{ color: delta >= 0 ? '#76b900' : '#ef4444', marginLeft: 6 }}>
                  {delta >= 0 ? '+' : ''}{(delta * 100).toFixed(2)}
                </span>
              </span>
            </div>
            <div style={{ height: 3, background: '#1e293b', borderRadius: 2 }}>
              <div style={{ height: '100%', width: `${child * 100}%`, background: BENCH_COLORS[k], borderRadius: 2 }} />
            </div>
          </div>
        );
      })}

      <div style={{ borderTop: '1px solid #1e293b', paddingTop: 14, marginTop: 8 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {[
            ['Method', node.method],
            ['Training Data', `${(node.trainingDataSize / 1000).toFixed(0)}K samples`],
            ['Duration', `${Math.floor(node.duration / 60)}m ${node.duration % 60}s`],
            ['Mutation Rate', node.mutationRate],
            ['Timestamp', new Date(node.timestamp).toLocaleDateString()],
          ].map(([label, val]) => (
            <div key={label} style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 11, color: '#475569', fontFamily: 'Outfit' }}>{label}</span>
              <span style={{ fontSize: 11, fontFamily: 'JetBrains Mono', color: '#94a3b8' }}>{val}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
