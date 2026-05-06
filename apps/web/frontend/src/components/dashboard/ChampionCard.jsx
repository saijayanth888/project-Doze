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
  const [apiError, setApiError] = useState(false);
  const [apiErrorKind, setApiErrorKind] = useState(null); // 'auth' | 'offline'

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const data = await apiFetch('/api/models/champion');
        if (cancelled) return;
        if (data && (data.generation ?? 0) > 0) {
          setChampion(data);
          setApiError(false);
          setApiErrorKind(null);
        } else {
          setChampion(null);
          setApiError(false);
          setApiErrorKind(null);
        }
      } catch (e) {
        if (cancelled) return;
        const st = e?.status;
        if (st === 404) {
          setChampion(null);
          setApiError(false);
          setApiErrorKind(null);
          return;
        }
        setChampion(null);
        setApiError(true);
        setApiErrorKind(st === 401 || st === 403 ? 'auth' : 'offline');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    setLoading(true);
    setApiError(false);
    setApiErrorKind(null);
    load();
    const iv = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(iv);
    };
  }, []);

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

  const championActions = (
    <div style={{ paddingTop: 12, marginTop: 12, borderTop: `1px solid ${C.border}`, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
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
        style={{
          padding: '5px 12px',
          background: 'transparent',
          color: C.txtS,
          border: `1px solid ${C.border}`,
          borderRadius: 4,
          cursor: 'pointer',
          fontFamily: F.ui,
          fontSize: 12,
        }}
      >
        View Lineage
      </button>
    </div>
  );

  if (apiError) {
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
          {apiErrorKind === 'auth'
            ? (
              <>
                API key missing or invalid — set <span style={{ fontFamily: F.mono }}>MODELFORGE_API_KEY</span> in Settings (or{' '}
                <span style={{ fontFamily: F.mono }}>VITE_MODELFORGE_API_KEY</span> at build time).
              </>
            )
            : 'API unreachable — check API base URL, network, and that the stack is up.'}
        </p>
        {championActions}
      </div>
    );
  }

  if (!champion) {
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
        <p style={{ fontFamily: F.ui, fontSize: 13, color: 'var(--text-muted)', marginTop: 12, lineHeight: 1.5 }}>
          No champion yet — start an evolution run to evolve your first model.
        </p>
        <div style={{ paddingTop: 12, marginTop: 12, borderTop: `1px solid ${C.border}`, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button
            type="button"
            onClick={() => navigate('/dashboard?startEvolution=1')}
            style={{
              padding: '5px 12px',
              background: C.acc,
              color: '#000',
              border: 'none',
              borderRadius: 4,
              cursor: 'pointer',
              fontFamily: F.ui,
              fontSize: 12,
              fontWeight: 700,
            }}
          >
            Start Evolution
          </button>
          {championActions}
        </div>
      </div>
    );
  }

  return (
    <div
      className="mf-card-hover"
      style={{
        background: C.bgC,
        border: `1px solid rgba(118,185,0,0.25)`,
        borderRadius: 8,
        padding: 18,
        height: '100%',
        boxSizing: 'border-box',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.txtM }}>
          Champion
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={C.acc} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
            <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6" />
            <path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18" />
            <path d="M4 22h16" />
            <path d="M18 2H6v7a6 6 0 0 0 12 0V2Z" />
          </svg>
          <span style={{ fontFamily: F.mono, fontSize: 11, color: C.acc, fontWeight: 600 }}>Gen {champion.generation}</span>
        </div>
      </div>

      <div style={{ marginBottom: 14 }}>
        <button
          type="button"
          onClick={() => navigate('/playground')}
          title="Open Playground"
          style={{
            fontFamily: F.mono,
            fontSize: 14,
            color: C.acc,
            fontWeight: 600,
            background: 'none',
            border: 'none',
            padding: 0,
            cursor: 'pointer',
            textAlign: 'left',
            display: 'block',
            textDecoration: 'underline',
            textDecorationColor: 'rgba(118,185,0,0.35)',
            textUnderlineOffset: 3,
          }}
        >
          {champion.base_model}
        </button>
        {champion.adapter_path ? (
          <div style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM, marginTop: 6, wordBreak: 'break-word' }}>
            Adapter: {champion.adapter_path}
          </div>
        ) : null}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 8 }}>
          <span style={{ fontFamily: F.mono, fontSize: '2rem', fontWeight: 500, color: C.txtP, lineHeight: 1 }}>{avgScore.toFixed(3)}</span>
          <span style={{ fontSize: 11, color: C.txtM }}>avg score</span>
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
