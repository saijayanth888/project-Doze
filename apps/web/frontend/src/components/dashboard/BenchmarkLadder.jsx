import { C, F } from '../../config/colors';

const BENCH_LABEL = {
  mmlu: 'MMLU',
  arc_challenge: 'ARC-Chal',
  hellaswag: 'HellaSwag',
  gsm8k: 'GSM8K',
  humaneval: 'HumanEval',
};

function statusGlyph(status) {
  if (status === 'done') return '✓';
  if (status === 'running') return '●';
  if (status === 'error') return '✗';
  return '○';
}

function statusColor(status) {
  if (status === 'done') return C.acc || '#22c55e';
  if (status === 'running') return '#38bdf8';
  if (status === 'error') return C.danger || '#ef4444';
  return C.txtM;
}

/**
 * Per-experiment benchmark progress for a campaign run. Replaces the
 * Evaluate→Identify→Curate→Train evolve-pipeline strip while a campaign is
 * in flight (those phases don't apply to lm-eval baselines).
 */
export default function BenchmarkLadder({ benchmarks }) {
  if (!Array.isArray(benchmarks) || benchmarks.length === 0) return null;

  return (
    <div style={{ marginBottom: 16 }}>
      <div
        style={{
          fontFamily: F.ui,
          fontSize: 9,
          fontWeight: 700,
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          color: C.txtM,
          marginBottom: 8,
        }}
      >
        Benchmark progress
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${benchmarks.length}, minmax(0, 1fr))`,
          gap: 8,
        }}
      >
        {benchmarks.map((b) => {
          const label = BENCH_LABEL[b.name] || b.name;
          const col = statusColor(b.status);
          const score = typeof b.score === 'number' ? b.score.toFixed(3) : null;
          const isRunning = b.status === 'running';
          return (
            <div
              key={b.name}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                padding: '8px 4px',
                borderRadius: 6,
                background: isRunning ? 'rgba(56,189,248,0.08)' : 'rgba(255,255,255,0.02)',
                border: `1px solid ${isRunning ? 'rgba(56,189,248,0.3)' : C.border}`,
              }}
            >
              <span
                style={{
                  fontFamily: F.mono,
                  fontSize: 18,
                  fontWeight: 700,
                  color: col,
                  lineHeight: 1,
                  animation: isRunning ? 'mf-pulse 1.6s ease-in-out infinite' : undefined,
                }}
              >
                {statusGlyph(b.status)}
              </span>
              <span
                style={{
                  fontFamily: F.mono,
                  fontSize: 10,
                  color: C.txtP,
                  marginTop: 6,
                  textAlign: 'center',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  maxWidth: '100%',
                }}
              >
                {label}
              </span>
              <span
                style={{
                  fontFamily: F.mono,
                  fontSize: 10,
                  color: score ? C.txtS : C.txtM,
                  marginTop: 2,
                  height: 12,
                }}
              >
                {score || (isRunning ? '…' : '')}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
