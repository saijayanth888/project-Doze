import { X } from 'lucide-react';
import { BENCH_COLORS } from '../../config/colors';

const KEYS = ['mmlu', 'arc_challenge', 'hellaswag', 'gsm8k', 'humaneval'];
const BENCHMARK_LABELS = {
  mmlu: 'MMLU',
  arc_challenge: 'ARC-C',
  hellaswag: 'HellaSwag',
  gsm8k: 'GSM8K',
  humaneval: 'HumanEval',
};

function scoresOf(n) {
  if (!n) return {};
  return n.scores || n.childScores || n.child_scores || {};
}

export default function LineageDetail({ node, onClose, allNodes = [] }) {
  if (!node) return null;

  const childScores = scoresOf(node);
  const parentId = node.parent_id ?? node.parentId;
  const parent = parentId ? allNodes.find(p => p.id === parentId) : null;
  const parentScores = parent ? scoresOf(parent) : (node.parentScores || node.parent_scores || {});

  const hasAnyChildBench = KEYS.some((k) => typeof childScores[k] === 'number');
  const avgChild = hasAnyChildBench
    ? KEYS.reduce((s, k) => s + (childScores[k] ?? 0), 0) / KEYS.length
    : typeof node.avg_score === 'number'
      ? node.avg_score
      : KEYS.reduce((s, k) => s + (childScores[k] ?? 0), 0) / KEYS.length;
  const hasParentScores = KEYS.some(k => typeof parentScores[k] === 'number');
  const avgParent = hasParentScores
    ? KEYS.reduce((s, k) => s + (parentScores[k] ?? 0), 0) / KEYS.length
    : null;

  const decisionReason = node.decision_reason ?? node.decisionReason ?? '—';
  const method = node.method ?? '—';
  const trainingDataSize = node.training_data_size ?? node.trainingDataSize;
  const duration = node.duration;
  const mutationRate = node.mutation_rate ?? node.mutationRate;
  const timestamp = node.timestamp;

  return (
    <div
      className="animate-slide-right"
      style={{
        position: 'absolute',
        top: 0,
        right: 0,
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
          <div style={{ fontSize: 11, color: '#64748b', fontFamily: 'JetBrains Mono, monospace', letterSpacing: 2 }}>
            GENERATION
          </div>
          <div style={{ fontFamily: 'Instrument Serif, Georgia, serif', fontSize: 24, color: '#f1f5f9' }}>
            Gen {node.generation}
          </div>
        </div>
        <button
          type="button"
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
        fontFamily: 'JetBrains Mono, monospace',
        color: node.promoted ? '#76b900' : '#ef4444',
        marginBottom: 16,
      }}>
        {node.promoted ? 'PROMOTED' : 'DISCARDED'}
      </div>

      <div style={{ fontSize: 12, color: '#94a3b8', fontFamily: 'Outfit, sans-serif', marginBottom: 16, lineHeight: 1.5 }}>
        {decisionReason}
      </div>

      <div style={{ fontSize: 11, color: '#64748b', fontFamily: 'JetBrains Mono, monospace', letterSpacing: 1, marginBottom: 10 }}>
        BENCHMARK SCORES
      </div>

      {!hasAnyChildBench ? (
        <div style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'Outfit, sans-serif', lineHeight: 1.45, marginBottom: 12 }}>
          {typeof node.avg_score === 'number' && node.avg_score > 0
            ? `Average (summary only): ${node.avg_score.toFixed(3)} — per-benchmark breakdown is stored when evaluation runs write to Postgres or when the champion registry row includes a full scores map.`
            : 'Per-benchmark scores are not stored for this snapshot. They appear after an evolution run completes evaluations (Postgres) or when registry.json lists scores for each benchmark key.'}
        </div>
      ) : null}

      {KEYS.map(k => {
        const child = childScores[k];
        const parent = parentScores[k];
        const delta = typeof child === 'number' && typeof parent === 'number' ? child - parent : null;
        return (
          <div key={k} style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ fontSize: 11, fontFamily: 'JetBrains Mono, monospace', color: '#64748b' }}>
                {BENCHMARK_LABELS[k]}
              </span>
              <span style={{ fontSize: 11, fontFamily: 'JetBrains Mono, monospace', color: BENCH_COLORS[k] }}>
                {typeof child === 'number' ? `${(child * 100).toFixed(1)}%` : '—'}
                {delta != null && (
                  <span style={{ color: delta >= 0 ? '#76b900' : '#ef4444', marginLeft: 6 }}>
                    {delta >= 0 ? '+' : ''}{(delta * 100).toFixed(2)}
                  </span>
                )}
              </span>
            </div>
            <div style={{ height: 3, background: '#1e293b', borderRadius: 2 }}>
              {typeof child === 'number' && (
                <div style={{ height: '100%', width: `${Math.min(100, child * 100)}%`, background: BENCH_COLORS[k], borderRadius: 2 }} />
              )}
            </div>
          </div>
        );
      })}

      <div style={{ borderTop: '1px solid #1e293b', paddingTop: 14, marginTop: 8 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {[
            ['Avg (this gen)', typeof avgChild === 'number' ? avgChild.toFixed(3) : '—'],
            ['Avg (parent)', avgParent != null ? avgParent.toFixed(3) : '—'],
            ['Method', method],
            ['Training Data', trainingDataSize != null ? `${(trainingDataSize / 1000).toFixed(0)}K samples` : '—'],
            ['Duration', typeof duration === 'number' ? `${Math.floor(duration / 60)}m ${duration % 60}s` : '—'],
            ['Mutation Rate', mutationRate != null ? String(mutationRate) : '—'],
            ['Timestamp', timestamp ? new Date(timestamp).toLocaleDateString() : '—'],
          ].map(([label, val]) => (
            <div key={label} style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 11, color: '#475569', fontFamily: 'Outfit, sans-serif' }}>{label}</span>
              <span style={{ fontSize: 11, fontFamily: 'JetBrains Mono, monospace', color: '#94a3b8' }}>{val}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
