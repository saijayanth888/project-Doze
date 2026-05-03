import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { C, F, BENCH_COLORS } from '../../config/colors';
import { apiFetch } from '../../config/api';
import { CHAMPION } from '../../config/mockData';

function ScoreBar({ label, value, color }) {
  const pct = Math.round(value * 100);
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
        <span style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM }}>{label}</span>
        <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtP, fontWeight: 500 }}>{value.toFixed(3)}</span>
      </div>
      <div style={{ height: 4, background: C.bgE, borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 2, transition: 'width 0.6s ease-out' }} />
      </div>
    </div>
  );
}

export default function ChampionCard() {
  const navigate = useNavigate();
  const [champion, setChampion] = useState(CHAMPION);

  useEffect(() => {
    apiFetch('/api/models/champion').then(setChampion).catch(() => {});
  }, []);

  const scoreVals = champion?.scores && typeof champion.scores === 'object'
    ? Object.values(champion.scores).filter((v) => typeof v === 'number')
    : [];
  const avgScore =
    champion?.avg_score ??
    (scoreVals.length ? scoreVals.reduce((a, b) => a + b, 0) / scoreVals.length : 0);

  return (
    <div className="mf-card-hover" style={{ background: C.bgC, border: `1px solid rgba(118,185,0,0.25)`, borderRadius: 8, padding: 18, height: '100%', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.txtM }}>Champion</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={C.acc} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
            <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/>
            <path d="M4 22h16"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/>
          </svg>
          <span style={{ fontFamily: F.mono, fontSize: 11, color: C.acc, fontWeight: 600 }}>Gen {champion?.generation}</span>
        </div>
      </div>

      <div style={{ marginBottom: 14 }}>
        <div style={{ fontFamily: F.mono, fontSize: 14, color: C.acc, fontWeight: 600 }}>{champion?.base_model}</div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 4 }}>
          <span style={{ fontFamily: F.mono, fontSize: '2rem', fontWeight: 500, color: C.txtP, lineHeight: 1 }}>{avgScore.toFixed(3)}</span>
          <span style={{ fontSize: 11, color: C.txtM }}>avg score</span>
        </div>
      </div>

      <div style={{ marginBottom: 12 }}>
        {champion?.scores && Object.entries(champion.scores).map(([bench, score]) => (
          <ScoreBar key={bench} label={bench} value={score} color={BENCH_COLORS[bench] || C.acc} />
        ))}
      </div>

      <div style={{ paddingTop: 12, borderTop: `1px solid ${C.border}`, display: 'flex', gap: 6 }}>
        <button type="button" onClick={() => navigate('/playground')} style={{ padding: '5px 12px', background: 'transparent', color: C.acc, border: `1px solid ${C.borderA}`, borderRadius: 4, cursor: 'pointer', fontFamily: F.ui, fontSize: 12, fontWeight: 500 }}>
          Run Inference
        </button>
        <button type="button" onClick={() => navigate('/lineage')} style={{ padding: '5px 12px', background: 'transparent', color: C.txtS, border: `1px solid ${C.border}`, borderRadius: 4, cursor: 'pointer', fontFamily: F.ui, fontSize: 12 }}>
          View Lineage
        </button>
      </div>
    </div>
  );
}
