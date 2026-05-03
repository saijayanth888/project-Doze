import { LineChart, Line, ResponsiveContainer, Tooltip } from 'recharts';
import { GENS, BENCHMARK_LABELS } from '../../config/mockData';
import { BENCH_COLORS } from '../../config/colors';

const KEYS = ['mmlu', 'arc_challenge', 'hellaswag', 'gsm8k', 'humaneval'];

const data = GENS.map(g => ({
  gen: g.generation,
  ...Object.fromEntries(KEYS.map(k => [k, parseFloat((g.childScores[k] * 100).toFixed(2))]))
}));

export default function TrendCharts() {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12 }}>
      {KEYS.map(k => {
        const vals = data.map(d => d[k]);
        const min = Math.min(...vals);
        const max = Math.max(...vals);
        const latest = vals[vals.length - 1];
        const first = vals[0];
        const delta = latest - first;

        return (
          <div key={k} style={{
            background: '#111827',
            border: '1px solid #1e293b',
            borderRadius: 10,
            padding: 14,
          }}>
            <div style={{ fontSize: 10, fontFamily: 'JetBrains Mono', color: '#64748b', letterSpacing: 1, marginBottom: 4 }}>
              {BENCHMARK_LABELS[k]}
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 8 }}>
              <span style={{ fontFamily: 'JetBrains Mono', fontSize: 20, fontWeight: 700, color: BENCH_COLORS[k] }}>
                {latest.toFixed(1)}%
              </span>
              <span style={{
                fontSize: 11,
                fontFamily: 'JetBrains Mono',
                color: delta >= 0 ? '#76b900' : '#ef4444',
              }}>
                {delta >= 0 ? '+' : ''}{delta.toFixed(1)}
              </span>
            </div>
            <ResponsiveContainer width="100%" height={60}>
              <LineChart data={data}>
                <Line
                  type="monotone"
                  dataKey={k}
                  stroke={BENCH_COLORS[k]}
                  strokeWidth={1.5}
                  dot={false}
                  isAnimationActive
                  animationDuration={1200}
                />
                <Tooltip
                  contentStyle={{
                    background: '#1a2235',
                    border: '1px solid #1e293b',
                    borderRadius: 6,
                    fontSize: 10,
                    fontFamily: 'JetBrains Mono',
                  }}
                  formatter={v => [`${v}%`]}
                  labelFormatter={l => `Gen ${l}`}
                />
              </LineChart>
            </ResponsiveContainer>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
              <span style={{ fontSize: 9, fontFamily: 'JetBrains Mono', color: '#475569' }}>
                Lo {min.toFixed(1)}
              </span>
              <span style={{ fontSize: 9, fontFamily: 'JetBrains Mono', color: '#475569' }}>
                Hi {max.toFixed(1)}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
