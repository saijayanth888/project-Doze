import { C, F, BENCH_COLORS } from '../config/colors';
import ScoreTrends from '../components/dashboard/ScoreTrends';
import HeatmapTable from '../components/benchmarks/HeatmapTable';
import { GENS } from '../config/mockData';

const BENCHMARKS = [
  { key: 'mmlu',         label: 'MMLU',         desc: 'Massive Multitask Language Understanding', weight: 0.25 },
  { key: 'arc_challenge',label: 'ARC-Challenge', desc: 'AI2 Reasoning Challenge',                  weight: 0.20 },
  { key: 'hellaswag',    label: 'HellaSwag',     desc: 'Commonsense Natural Language Inference',   weight: 0.20 },
  { key: 'gsm8k',        label: 'GSM8K',         desc: 'Grade School Math Word Problems',          weight: 0.20 },
  { key: 'humaneval',    label: 'HumanEval',     desc: 'Python Code Generation',                   weight: 0.15 },
];

export default function BenchmarksPage() {
  const latest = GENS[GENS.length - 1];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Benchmark summary cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 12 }}>
        {BENCHMARKS.map(b => {
          const score = latest?.child_scores?.[b.key] || 0;
          return (
            <div key={b.key} style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: '14px 16px', animation: 'slide-up-fade 0.4s ease-out both' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 8 }}>
                <div style={{ width: 6, height: 6, borderRadius: '50%', background: BENCH_COLORS[b.key] }} />
                <span style={{ fontFamily: F.ui, fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: C.txtM }}>{b.label}</span>
              </div>
              <div style={{ fontFamily: F.mono, fontSize: '1.6rem', fontWeight: 500, color: C.txtP, lineHeight: 1, marginBottom: 4 }}>{score.toFixed(3)}</div>
              <div style={{ fontFamily: F.ui, fontSize: 11, color: C.txtM, lineHeight: 1.4, marginBottom: 8 }}>{b.desc}</div>
              <div style={{ fontFamily: F.mono, fontSize: 9, color: C.txtM }}>weight: {b.weight}</div>
              <div style={{ marginTop: 6, height: 3, background: C.bgE, borderRadius: 2, overflow: 'hidden' }}>
                <div style={{ width: `${score * 100}%`, height: '100%', background: BENCH_COLORS[b.key], borderRadius: 2 }} />
              </div>
            </div>
          );
        })}
      </div>

      {/* Trends */}
      <ScoreTrends />

      {/* Heatmap */}
      <HeatmapTable />
    </div>
  );
}
