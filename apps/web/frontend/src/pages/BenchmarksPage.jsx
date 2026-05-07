import { useCallback, useEffect, useMemo, useState } from 'react';
import { C, F, BENCH_COLORS } from '../config/colors';
import ScoreTrends from '../components/dashboard/ScoreTrends';
import HeatmapTable from '../components/benchmarks/HeatmapTable';
import { apiFetch } from '../config/api';
import { BENCHMARK_INFO } from '../data/benchmarkInfo';
import InfoTooltip from '../components/shared/InfoTooltip';

const BENCHMARKS = [
  { key: 'mmlu', label: 'MMLU', desc: 'Massive Multitask Language Understanding', weight: 0.25 },
  { key: 'arc_challenge', label: 'ARC-Challenge', desc: 'AI2 Reasoning Challenge', weight: 0.2 },
  { key: 'hellaswag', label: 'HellaSwag', desc: 'Commonsense Natural Language Inference', weight: 0.2 },
  { key: 'gsm8k', label: 'GSM8K', desc: 'Grade School Math Word Problems', weight: 0.2 },
  { key: 'humaneval', label: 'HumanEval', desc: 'Python Code Generation', weight: 0.15 },
];

function latestScoresFromGenerations(generations) {
  if (!generations?.length) return {};
  const sorted = [...generations].sort((a, b) => a.generation - b.generation);
  const latest = sorted[sorted.length - 1];
  return latest?.scores && typeof latest.scores === 'object' ? latest.scores : {};
}

export default function BenchmarksPage() {
  const [generations, setGenerations] = useState([]);

  const loadGenerations = useCallback(async () => {
    try {
      const data = await apiFetch('/api/eval/generations');
      setGenerations(Array.isArray(data) ? data : []);
    } catch {
      setGenerations([]);
    }
  }, []);

  useEffect(() => {
    loadGenerations();
    const iv = setInterval(loadGenerations, 12_000);
    return () => clearInterval(iv);
  }, [loadGenerations]);

  const latestScores = useMemo(
    () => latestScoresFromGenerations(generations),
    [generations],
  );

  const heatmapRows = useMemo(
    () =>
      generations.map((g) => ({
        generation: g.generation,
        promoted: !!g.promoted,
        childScores: g.scores && typeof g.scores === 'object' ? g.scores : {},
      })),
    [generations],
  );

  const hasAnyBenchScore = useMemo(
    () => BENCHMARKS.some((b) => Number(latestScores[b.key] ?? 0) > 0),
    [latestScores],
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {!hasAnyBenchScore ? (
        <div
          style={{
            fontFamily: F.ui,
            fontSize: 13,
            color: C.warning,
            lineHeight: 1.5,
            padding: '12px 14px',
            background: C.warningDim,
            border: `1px solid ${C.warning}`,
            borderRadius: 8,
          }}
        >
          No per-benchmark scores are available yet. The cards below stay at 0.000 until evaluation writes scores to Postgres
          (during evolution) or your champion row in <span style={{ fontFamily: F.mono }}>registry.json</span> includes a non-empty{' '}
          <span style={{ fontFamily: F.mono }}>scores</span> object (e.g. mmlu, gsm8k). Run a full evolution with benchmarks enabled, or
          attach scores when promoting an adapter.
        </div>
      ) : null}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 12 }}>
        {BENCHMARKS.map((b) => {
          const score = Number(latestScores[b.key] ?? 0);
          return (
            <div
              key={b.key}
              style={{
                background: C.bgC,
                border: `1px solid ${C.border}`,
                borderRadius: 8,
                padding: '14px 16px',
                animation: 'slide-up-fade 0.4s ease-out both',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 8 }}>
                <div
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: '50%',
                    background: BENCH_COLORS[b.key],
                  }}
                />
                <span
                  style={{
                    fontFamily: F.ui,
                    fontSize: 10,
                    fontWeight: 700,
                    letterSpacing: '0.1em',
                    textTransform: 'uppercase',
                    color: C.txtM,
                  }}
                >
                  {b.label}
                  <InfoTooltip info={BENCHMARK_INFO[b.key]} size={11} />
                </span>
              </div>
              <div
                style={{
                  fontFamily: F.mono,
                  fontSize: '1.6rem',
                  fontWeight: 500,
                  color: C.txtP,
                  lineHeight: 1,
                  marginBottom: 4,
                }}
              >
                {Number(score).toFixed(3)}
              </div>
              <div
                style={{
                  fontFamily: F.ui,
                  fontSize: 11,
                  color: C.txtM,
                  lineHeight: 1.4,
                  marginBottom: 8,
                }}
              >
                {b.desc}
              </div>
              <div style={{ fontFamily: F.mono, fontSize: 9, color: C.txtM }}>
                weight: {b.weight}
              </div>
              <div style={{ marginTop: 6, height: 3, background: C.bgE, borderRadius: 2, overflow: 'hidden' }}>
                <div
                  style={{
                    width: `${Math.min(100, Number(score) * 100)}%`,
                    height: '100%',
                    background: BENCH_COLORS[b.key],
                    borderRadius: 2,
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>

      <ScoreTrends />

      <HeatmapTable rows={heatmapRows} />
    </div>
  );
}
