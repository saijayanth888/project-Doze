import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { ArrowDownRight, ArrowRight, ArrowUpRight, Trophy } from 'lucide-react';
import { C, F, BENCH_COLORS } from '../../config/colors';
import { apiFetch } from '../../config/api';
import { BENCHMARK_INFO } from '../../data/benchmarkInfo';
import InfoTooltip from '../shared/InfoTooltip';

const SCORES_POLL_MS = 5000;
const TICK_STROKE = C.borderL;
const FALLBACK_BENCH_COLORS = ['#94a3b8', '#a78bfa', '#fb923c', '#2dd4bf', '#e879f9', '#facc15'];

/** Folds the flat trends list into one row per generation with one column per
 * benchmark. Used by both the wide chart at the top and the per-benchmark
 * sparklines below. */
function buildChartDataFromTrends(trends) {
  const byGen = {};
  (trends || []).forEach((t) => {
    const g = t.generation;
    if (!byGen[g]) byGen[g] = { generation: g, promoted: !!t.promoted };
    if (t.benchmark != null) {
      byGen[g][t.benchmark] = t.child_score;
      byGen[g][`${t.benchmark}__parent`] = t.parent_score;
      byGen[g][`${t.benchmark}__delta`] = t.delta;
    }
    byGen[g].promoted = byGen[g].promoted || !!t.promoted;
  });
  const rows = Object.values(byGen).sort((a, b) => a.generation - b.generation);
  // Compute per-generation average across all numeric benchmarks.
  for (const r of rows) {
    const vals = Object.entries(r)
      .filter(([k, v]) => k !== 'generation' && k !== 'promoted' && !k.includes('__') && typeof v === 'number')
      .map(([, v]) => v);
    r.avg = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
  }
  return rows;
}

function yDomainFromRows(rows) {
  if (!rows?.length) return [0, 1];
  let min = Infinity;
  let max = -Infinity;
  for (const row of rows) {
    Object.entries(row).forEach(([key, val]) => {
      if (key === 'generation' || key === 'promoted' || key.includes('__')) return;
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

function benchColorsForData(dataRows) {
  const keys = new Set();
  for (const row of dataRows || []) {
    Object.keys(row).forEach((k) => {
      if (k !== 'generation' && k !== 'promoted' && k !== 'avg' && !k.includes('__')) {
        keys.add(k);
      }
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

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div
      style={{
        background: C.bgE,
        border: `1px solid ${C.borderL}`,
        borderRadius: 6,
        padding: '10px 14px',
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
      }}
    >
      <div style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM, marginBottom: 6 }}>Gen {label}</div>
      {payload
        .filter((p) => !p.dataKey?.includes('__') && p.dataKey !== 'avg' && typeof p.value === 'number')
        .map((p) => (
          <div key={p.dataKey} style={{ display: 'flex', justifyContent: 'space-between', gap: 16, marginBottom: 2 }}>
            <span style={{ fontFamily: F.mono, fontSize: 11, color: p.color }}>{p.dataKey}</span>
            <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtP, fontWeight: 600 }}>
              {p.value?.toFixed(3)}
            </span>
          </div>
        ))}
    </div>
  );
};

/** Big arrow + delta number — color encodes direction.
 * Used in summary KPIs and per-benchmark cards. */
function DeltaPill({ delta, fontSize = 11 }) {
  if (delta == null || !Number.isFinite(delta)) return null;
  const tone = delta > 0.001 ? C.success : delta < -0.001 ? C.danger : C.txtM;
  const Arrow = delta > 0.001 ? ArrowUpRight : delta < -0.001 ? ArrowDownRight : ArrowRight;
  const sign = delta > 0 ? '+' : '';
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 2,
        padding: '1px 6px',
        borderRadius: 999,
        fontFamily: F.mono,
        fontSize,
        color: tone,
        background: `${tone}1a`,
        border: `1px solid ${tone}33`,
        fontWeight: 600,
      }}
    >
      <Arrow size={fontSize} />
      {sign}
      {delta.toFixed(3)}
    </span>
  );
}

/** A single benchmark card: current score (filled bar to 1.0), delta vs parent,
 * and a baseline sparkline across all generations seen so far. */
function BenchCard({ benchmark, color, rows }) {
  const last = rows[rows.length - 1];
  const cur = typeof last?.[benchmark] === 'number' ? last[benchmark] : null;
  const delta = typeof last?.[`${benchmark}__delta`] === 'number' ? last[`${benchmark}__delta`] : null;
  const sparkline = rows.map((r, i) => ({ x: i, y: typeof r[benchmark] === 'number' ? r[benchmark] : 0 }));
  const fillPct = cur != null ? Math.max(0, Math.min(1, cur)) * 100 : 0;
  return (
    <div
      style={{
        background: C.bgC,
        border: `1px solid ${C.border}`,
        borderRadius: 8,
        padding: '12px 14px',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span
          style={{
            fontFamily: F.mono,
            fontSize: 10,
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
            color,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <span style={{ width: 6, height: 6, borderRadius: 999, background: color }} />
          {benchmark}
          <InfoTooltip info={BENCHMARK_INFO[benchmark]} size={11} />
        </span>
        {delta != null ? <DeltaPill delta={delta} fontSize={10} /> : null}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <span style={{ fontFamily: F.mono, fontSize: 22, color: C.txtP, fontWeight: 500 }}>
          {cur != null ? cur.toFixed(3) : '—'}
        </span>
        <span style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM }}>/ 1.000</span>
      </div>
      {/* Bar to perfect score */}
      <div
        style={{
          position: 'relative',
          height: 4,
          background: 'rgba(255,255,255,0.04)',
          borderRadius: 999,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            position: 'absolute',
            inset: 0,
            width: `${fillPct}%`,
            background: `linear-gradient(90deg, ${color}aa, ${color})`,
            borderRadius: 999,
          }}
        />
      </div>
      {/* Sparkline — single point uses a flat baseline so the user still sees something. */}
      <div style={{ height: 32 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={sparkline.length === 1 ? [{ x: 0, y: sparkline[0].y }, { x: 1, y: sparkline[0].y }] : sparkline} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
            <Area type="monotone" dataKey="y" stroke={color} strokeWidth={1.5} fill={`${color}33`} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export default function ScoreTrends() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  const loadTrends = useCallback(async () => {
    try {
      const d = await apiFetch('/api/eval/scores');
      const trends = d?.trends;
      setData(trends?.length ? buildChartDataFromTrends(trends) : []);
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
      if (!cancelled) await loadTrends();
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

  // Top-line summary: latest gen avg + delta vs previous gen avg.
  const summary = useMemo(() => {
    if (!data.length) return null;
    const last = data[data.length - 1];
    const prev = data.length >= 2 ? data[data.length - 2] : null;
    const numBench = benchKeys.length;
    const best = benchKeys
      .map((b) => ({ b, v: typeof last[b] === 'number' ? last[b] : -Infinity }))
      .sort((a, c) => c.v - a.v)[0];
    const worst = benchKeys
      .map((b) => ({ b, v: typeof last[b] === 'number' ? last[b] : Infinity }))
      .sort((a, c) => a.v - c.v)[0];
    return {
      gen: last.generation,
      avg: last.avg,
      promoted: !!last.promoted,
      avgDelta: prev?.avg != null && last.avg != null ? last.avg - prev.avg : null,
      generations: data.length,
      benchmarks: numBench,
      best: best && Number.isFinite(best.v) ? best : null,
      worst: worst && Number.isFinite(worst.v) ? worst : null,
    };
  }, [data, benchKeys]);

  return (
    <div
      className="mf-card-hover"
      style={{
        background: C.bgC,
        border: `1px solid ${C.border}`,
        borderRadius: 8,
        padding: 16,
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
      }}
    >
      {/* Header strip */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <span
          style={{
            fontFamily: F.ui,
            fontSize: 13,
            fontWeight: 700,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            color: C.txtM,
          }}
        >
          Score Trends
        </span>
        {summary ? (
          <div style={{ display: 'flex', gap: 16, alignItems: 'center', fontFamily: F.mono, fontSize: 11, color: C.txtM }}>
            <span title="Generations evaluated so far">
              {summary.generations} gen{summary.generations === 1 ? '' : 's'}
            </span>
            <span>·</span>
            <span title="Benchmarks tracked">
              {summary.benchmarks} bench
            </span>
            {summary.best ? (
              <>
                <span>·</span>
                <span title="Best benchmark this gen">
                  best: <span style={{ color: lineColors[summary.best.b] || C.acc }}>{summary.best.b}</span>{' '}
                  {summary.best.v.toFixed(3)}
                </span>
              </>
            ) : null}
            {summary.worst && summary.worst.b !== summary.best?.b ? (
              <>
                <span>·</span>
                <span title="Weakest benchmark this gen — likely target of next curation">
                  weak: <span style={{ color: lineColors[summary.worst.b] || C.danger }}>{summary.worst.b}</span>{' '}
                  {summary.worst.v.toFixed(3)}
                </span>
              </>
            ) : null}
          </div>
        ) : null}
      </div>

      {loading && !hasData ? (
        <div style={{ fontFamily: F.ui, fontSize: 12, color: C.txtM, padding: '24px 8px' }}>Loading trends…</div>
      ) : !hasData ? (
        <div
          style={{
            fontFamily: F.ui,
            fontSize: 13,
            color: C.txtM,
            padding: '40px 16px',
            textAlign: 'center',
            border: `1px dashed ${C.border}`,
            borderRadius: 6,
          }}
        >
          Score trends will appear after the first evolution run.
        </div>
      ) : (
        <>
          {/* Headline KPI band */}
          {summary ? (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
                gap: 12,
              }}
            >
              <div style={{ padding: '10px 14px', background: C.bgI, border: `1px solid ${C.border}`, borderRadius: 8 }}>
                <div style={{ fontFamily: F.mono, fontSize: 9, color: C.txtM, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                  Latest gen
                </div>
                <div style={{ fontFamily: F.mono, fontSize: 22, color: summary.promoted ? C.acc : C.txtP, marginTop: 2 }}>
                  Gen {summary.gen}
                </div>
                <div
                  style={{
                    marginTop: 4,
                    fontFamily: F.mono,
                    fontSize: 10,
                    color: summary.promoted ? C.acc : C.txtM,
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 4,
                  }}
                >
                  {summary.promoted ? <Trophy size={11} /> : null}
                  {summary.promoted ? 'promoted' : 'discarded'}
                </div>
              </div>

              <div style={{ padding: '10px 14px', background: C.bgI, border: `1px solid ${C.border}`, borderRadius: 8 }}>
                <div style={{ fontFamily: F.mono, fontSize: 9, color: C.txtM, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                  Avg score
                </div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                  <span style={{ fontFamily: F.mono, fontSize: 22, color: C.txtP, marginTop: 2 }}>
                    {summary.avg != null ? summary.avg.toFixed(3) : '—'}
                  </span>
                  {summary.avgDelta != null ? <DeltaPill delta={summary.avgDelta} fontSize={10} /> : null}
                </div>
                <div style={{ marginTop: 4, fontFamily: F.mono, fontSize: 10, color: C.txtM }}>
                  vs previous gen
                </div>
              </div>

              <div style={{ padding: '10px 14px', background: C.bgI, border: `1px solid ${C.border}`, borderRadius: 8 }}>
                <div style={{ fontFamily: F.mono, fontSize: 9, color: C.txtM, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                  Headroom to 1.000
                </div>
                <div style={{ fontFamily: F.mono, fontSize: 22, color: C.warning, marginTop: 2 }}>
                  {summary.avg != null ? (1 - summary.avg).toFixed(3) : '—'}
                </div>
                <div style={{ marginTop: 4, fontFamily: F.mono, fontSize: 10, color: C.txtM }}>
                  room to improve
                </div>
              </div>
            </div>
          ) : null}

          {/* Per-benchmark cards with sparklines */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
              gap: 10,
            }}
          >
            {benchKeys.map((b) => (
              <BenchCard key={b} benchmark={b} color={lineColors[b] || BENCH_COLORS[b] || C.ind} rows={data} />
            ))}
          </div>

          {/* Big trend chart — only meaningful with 2+ generations, but still
               renders the single-gen marker dots so the user can see something. */}
          <div style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 6, right: 12, bottom: 18, left: 6 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.border} vertical={false} />
                <XAxis
                  dataKey="generation"
                  tick={{ fontFamily: F.mono, fontSize: 10, fill: C.txtM }}
                  axisLine={{ stroke: C.border }}
                  tickLine={{ stroke: TICK_STROKE }}
                  label={{ value: 'generation', position: 'insideBottom', offset: -2, fill: C.txtM, fontSize: 10, fontFamily: F.mono }}
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
                {/* Average score as a thicker accent line */}
                <Line type="monotone" dataKey="avg" stroke={C.acc} strokeWidth={2.5} dot={{ r: 4, fill: C.acc, strokeWidth: 0 }} />
                {benchKeys.map((bench) => {
                  const color = lineColors[bench] || BENCH_COLORS[bench] || C.ind;
                  return (
                    <Line
                      key={bench}
                      type="monotone"
                      dataKey={bench}
                      stroke={color}
                      strokeWidth={1.5}
                      dot={{ r: 3, fill: color, strokeWidth: 0 }}
                      activeDot={{ r: 5, fill: color, strokeWidth: 0 }}
                    />
                  );
                })}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
}
