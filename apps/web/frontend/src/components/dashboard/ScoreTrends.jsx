import { useEffect, useState } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer } from 'recharts';
import { C, F, BENCH_COLORS } from '../../config/colors';
import { apiFetch } from '../../config/api';

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

export default function ScoreTrends() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    apiFetch('/api/eval/scores')
      .then((d) => {
        if (cancelled) return;
        const trends = d?.trends;
        if (trends?.length) {
          setData(buildChartDataFromTrends(trends));
        } else {
          setData([]);
        }
      })
      .catch(() => {
        if (!cancelled) setData([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const promotedGens = data.filter((d) => d.promoted).map((d) => d.generation);
  const hasData = data.length > 0;

  return (
    <div className="mf-card-hover" style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: '16px 16px 8px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.txtM }}>Score Trends</span>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {Object.entries(BENCH_COLORS).map(([b, clr]) => (
            <div key={b} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div style={{ width: 16, height: 2, background: clr, borderRadius: 1 }} />
              <span style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM }}>{b}</span>
            </div>
          ))}
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
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={C.border} vertical={false} />
            <XAxis dataKey="generation" tick={{ fontFamily: F.mono, fontSize: 10, fill: C.txtM }} axisLine={{ stroke: C.border }} tickLine={false} />
            <YAxis domain={[0.3, 0.9]} tick={{ fontFamily: F.mono, fontSize: 10, fill: C.txtM }} axisLine={false} tickLine={false} tickFormatter={(v) => v.toFixed(2)} />
            <Tooltip content={<CustomTooltip />} />
            {promotedGens.map((gen) => (
              <ReferenceLine key={gen} x={gen} stroke="rgba(118,185,0,0.2)" strokeDasharray="3 3" />
            ))}
            {Object.entries(BENCH_COLORS).map(([bench, color]) => (
              <Line key={bench} type="monotone" dataKey={bench} stroke={color} strokeWidth={1.5} dot={false} activeDot={{ r: 4, fill: color, strokeWidth: 0 }} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
