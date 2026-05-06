import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { C, F, BENCH_COLORS } from '../../config/colors';
import { apiFetch } from '../../config/api';

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
  const [champion, setChampion] = useState(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setFetchError(null);
    apiFetch('/api/models/champion')
      .then((data) => {
        if (!cancelled) {
          setChampion(data);
          setFetchError(null);
        }
      })
      .catch((e) => {
        if (cancelled) return;
        setChampion(null);
        if (e?.status === 404) setFetchError('none');
        else setFetchError('offline');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const isRealChampion = champion && (champion.generation ?? 0) > 0;
  const isBaselineOnly = champion && (champion.generation ?? 0) === 0;

  const scoreVals =
    champion?.scores && typeof champion.scores === 'object'
      ? Object.values(champion.scores).filter((v) => typeof v === 'number')
      : [];
  const avgScore =
    champion?.avg_score ??
    (scoreVals.length ? scoreVals.reduce((a, b) => a + b, 0) / scoreVals.length : 0);

  if (loading) {
    return (
      <div
        className="mf-card-hover"
        style={{
          background: C.bgC,
          border: `1px solid ${C.border}`,
          borderRadius: 8,
          padding: 18,
          height: '100%',
          boxSizing: 'border-box',
          fontFamily: F.ui,
          fontSize: 13,
          color: C.txtM,
        }}
      >
        Loading champion…
      </div>
    );
  }

  if (fetchError === 'offline') {
    return (
      <div
        className="mf-card-hover"
        style={{
          background: C.bgC,
          border: `1px solid ${C.border}`,
          borderRadius: 8,
          padding: 18,
          height: '100%',
          boxSizing: 'border-box',
        }}
      >
        <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.txtM }}>
          Champion
        </span>
        <p style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM, marginTop: 12, lineHeight: 1.5 }}>
          Connect to API to view champion (check API base URL and network).
        </p>
      </div>
    );
  }

  if (fetchError === 'none' || !champion) {
    return (
      <div
        className="mf-card-hover"
        style={{
          background: C.bgC,
          border: `1px solid ${C.border}`,
          borderRadius: 8,
          padding: 18,
          height: '100%',
          boxSizing: 'border-box',
        }}
      >
        <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.txtM }}>
          Champion
        </span>
        <p style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM, marginTop: 12, lineHeight: 1.5 }}>
          No evolution champion yet — run evolution and promote a model to see scores here.
        </p>
      </div>
    );
  }

  return (
    <div
      className="mf-card-hover"
      style={{
        background: C.bgC,
        border: `1px solid rgba(118,185,0,${isRealChampion ? '0.25' : '0.12'})`,
        borderRadius: 8,
        padding: 18,
        height: '100%',
        boxSizing: 'border-box',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.txtM }}>
          {isBaselineOnly ? 'Base model' : 'Champion'}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {isRealChampion ? (
            <>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={C.acc} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
                <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6" />
                <path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18" />
                <path d="M4 22h16" />
                <path d="M18 2H6v7a6 6 0 0 0 12 0V2Z" />
              </svg>
              <span style={{ fontFamily: F.mono, fontSize: 11, color: C.acc, fontWeight: 600 }}>Gen {champion.generation}</span>
            </>
          ) : (
            <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM }}>baseline</span>
          )}
        </div>
      </div>

      <div style={{ marginBottom: 14 }}>
        <div style={{ fontFamily: F.mono, fontSize: 14, color: isRealChampion ? C.acc : C.txtS, fontWeight: 600 }}>
          {isBaselineOnly ? 'Base Model (no champion yet)' : champion.base_model}
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 8 }}>
          <span style={{ fontFamily: F.mono, fontSize: '2rem', fontWeight: 500, color: C.txtP, lineHeight: 1 }}>{avgScore.toFixed(3)}</span>
          <span style={{ fontSize: 11, color: C.txtM }}>{isBaselineOnly ? 'avg score (baseline)' : 'avg score'}</span>
        </div>
      </div>

      <div style={{ marginBottom: 12 }}>
        {champion.scores &&
          Object.entries(champion.scores).map(([bench, score]) => (
            <ScoreBar key={bench} label={bench} value={score} color={BENCH_COLORS[bench] || C.acc} />
          ))}
      </div>

      <div style={{ paddingTop: 12, borderTop: `1px solid ${C.border}`, display: 'flex', gap: 6 }}>
        <button
          type="button"
          onClick={() => navigate('/playground')}
          style={{
            padding: '5px 12px',
            background: 'transparent',
            color: C.acc,
            border: `1px solid ${C.borderA}`,
            borderRadius: 4,
            cursor: 'pointer',
            fontFamily: F.ui,
            fontSize: 12,
            fontWeight: 500,
          }}
        >
          Run Inference
        </button>
        <button
          type="button"
          onClick={() => navigate('/lineage')}
          style={{ padding: '5px 12px', background: 'transparent', color: C.txtS, border: `1px solid ${C.border}`, borderRadius: 4, cursor: 'pointer', fontFamily: F.ui, fontSize: 12 }}
        >
          View Lineage
        </button>
      </div>
    </div>
  );
}
