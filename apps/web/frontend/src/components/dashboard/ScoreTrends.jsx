import { useCallback, useEffect, useMemo, useState } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer } from 'recharts';
import { C, F, BENCH_COLORS } from '../../config/colors';
import { apiFetch } from '../../config/api';

const TICK_STROKE = C.borderL;

function yDomainFromRows(rows) {
  if (!rows?.length) return [0, 1];
  let min = Infinity;
  let max = -Infinity;
  for (const row of rows) {
    Object.entries(row).forEach(([key, val]) => {
      if (key === 'generation' || key === 'promoted') return;
      if (typeof val === 'number' && Number.isFinite(val)) {
        min = Math.min(min, val);
        max = Math.max(max, val);
      }
    });
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
  if (min === max) {
    const pad = min === 0 ? 0.08 : Math.abs(min) * 0.12;
    return [Math.max(0, min - pad), Math.min(1, max + pad)];
  }
  const pad = Math.max((max - min) * 0.12, 0.02);
  return [Math.max(0, min - pad), Math.min(1, max + pad)];
}

function buildChartDataFromTrends(trends) {
  const byGen = {};
  (trends || []).forEach((t) => {
    const g = t.generation;
    if (!byGen[g]) {
      byGen[g] = { generation: g, promoted: !!t.promoted };
    }
    if (t.benchmark != null) {
      byGen[g][t.benchmark] = t.child_score;
    }
    byGen[g].promoted = byGen[g].promoted || !!t.promoted;
  });
  return Object.values(byGen).sort((a, b) => a.generation - b.generation);
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: C.bgE, border: `1px solid ${C.borderL}`, borderRadius: 6, padding: '10px 14px', boxShadow: '0 8px 32px rgba(0,0,0,0.5)' }}>
      <div style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM, marginBottom: 6 }}>Gen {label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} style={{ display: 'flex', justifyContent: 'space-between', gap: 16, marginBottom: 2 }}>
          <span style={{ fontFamily: F.mono, fontSize: 11, color: p.color }}>{p.dataKey}</span>
          <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtP, fontWeight: 600 }}>{p.value?.toFixed(3)}</span>
        </div>
      ))}
    </div>
  );
};

const SCORES_POLL_MS = 5000;

const FALLBACK_BENCH_COLORS = ['#94a3b8', '#a78bfa', '#fb923c', '#2dd4bf', '#e879f9', '#facc15'];

function benchColorsForData(dataRows) {
  const keys = new Set();
  for (const row of dataRows || []) {
    Object.keys(row).forEach((k) => {
      if (k !== 'generation' && k !== 'promoted') keys.add(k);
    });
  }
  const out = { ...BENCH_COLORS };
  let i = 0;
  for (const k of keys) {
    if (!out[k]) {
      out[k] = FALLBACK_BENCH_COLORS[i % FALLBACK_BENCH_COLORS.length];
      i += 1;
    }
  }
  return { keys: Array.from(keys).sort(), colors: out };
}

export default function ScoreTrends() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  const loadTrends = useCallback(async () => {
    try {
      const d = await apiFetch('/api/eval/scores');
      const trends = d?.trends;
      if (trends?.length) {
        setData(buildChartDataFromTrends(trends));
      } else {
        setData([]);
      }
    } catch {
      setData([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      if (cancelled) return;
      await loadTrends();
    })();
    const iv = setInterval(() => {
      if (!cancelled) loadTrends();
    }, SCORES_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(iv);
    };
  }, [loadTrends]);

  const promotedGens = data.filter((d) => d.promoted).map((d) => d.generation);
  const hasData = data.length > 0;
  const yDomain = useMemo(() => yDomainFromRows(data), [data]);
  const { keys: benchKeys, colors: lineColors } = useMemo(() => benchColorsForData(data), [data]);

  return (
    <div className="mf-card-hover" style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: '16px 16px 8px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.txtM }}>Score Trends</span>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {(benchKeys.length ? benchKeys : Object.keys(BENCH_COLORS)).map((b) => {
            const clr = lineColors[b] || BENCH_COLORS[b] || C.txtM;
            return (
              <div key={b} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <div style={{ width: 16, height: 2, background: clr, borderRadius: 1 }} />
                <span style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM }}>{b}</span>
              </div>
            );
          })}
        </div>
      </div>
      {loading ? (
        <div style={{ fontFamily: F.ui, fontSize: 12, color: C.txtM, padding: '24px 8px' }}>Loading trends…</div>
      ) : !hasData ? (
        <div
          style={{
            fontFamily: F.ui,
            fontSize: 13,
            color: C.txtM,
            padding: '48px 16px',
            textAlign: 'center',
            border: `1px dashed ${C.border}`,
            borderRadius: 6,
            marginBottom: 8,
          }}
        >
          Score trends will appear after the first evolution run.
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={data} margin={{ top: 10, right: 12, bottom: 18, left: 6 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={C.border} vertical={false} />
            <XAxis
              dataKey="generation"
              tick={{ fontFamily: F.mono, fontSize: 10, fill: C.txtM }}
              axisLine={{ stroke: C.border }}
              tickLine={{ stroke: TICK_STROKE }}
            />
            <YAxis
              domain={yDomain}
              width={44}
              tick={{ fontFamily: F.mono, fontSize: 10, fill: C.txtM }}
              axisLine={{ stroke: C.border }}
              tickLine={{ stroke: TICK_STROKE }}
              tickFormatter={(v) => v.toFixed(2)}
            />
            <Tooltip content={<CustomTooltip />} />
            {promotedGens.map((gen) => (
              <ReferenceLine key={gen} x={gen} stroke="rgba(118,185,0,0.2)" strokeDasharray="3 3" />
            ))}
            {benchKeys.map((bench) => {
              const color = lineColors[bench] || BENCH_COLORS[bench] || C.ind;
              return (
                <Line key={bench} type="monotone" dataKey={bench} stroke={color} strokeWidth={1.5} dot={false} activeDot={{ r: 4, fill: color, strokeWidth: 0 }} />
              );
            })}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
