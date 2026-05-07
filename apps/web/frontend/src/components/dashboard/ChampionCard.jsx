import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { MessageSquare, GitCompare, Trophy, GitBranch } from 'lucide-react';
import { C, F, BENCH_COLORS } from '../../config/colors';
import { apiFetch } from '../../config/api';
import { BENCHMARK_INFO, CONCEPT_INFO } from '../../data/benchmarkInfo';
import InfoTooltip from '../shared/InfoTooltip';

function ScoreBar({ label, value, color }) {
  const pct = Math.round(value * 100);
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
        <span style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          {label}<InfoTooltip info={BENCHMARK_INFO[label]} size={11} />
        </span>
        <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtP, fontWeight: 500 }}>{value.toFixed(3)}</span>
      </div>
      <div style={{ height: 4, background: C.bgE, borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 2, transition: 'width 0.6s ease-out' }} />
      </div>
    </div>
  );
}

/** Compact "x ago" label for ISO timestamps. Returns '—' for missing/invalid input. */
function relativeTime(iso) {
  if (!iso) return '—';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  const diffSec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  const diffD = Math.floor(diffH / 24);
  if (diffD < 30) return `${diffD}d ago`;
  const diffMo = Math.floor(diffD / 30);
  if (diffMo < 12) return `${diffMo}mo ago`;
  const diffY = Math.floor(diffD / 365);
  return `${diffY}y ago`;
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

  // Used only by the apiError branch — empty + rendered branches define their own actions.
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
        <p style={{ fontFamily: F.ui, fontSize: 13, color: C.txtP, marginTop: 12, marginBottom: 8, lineHeight: 1.5, fontWeight: 600 }}>
          No champion yet.
        </p>
        <p style={{ fontFamily: F.ui, fontSize: 12, color: C.txtM, marginTop: 0, marginBottom: 14, lineHeight: 1.6 }}>
          ModelForge promotes an adapter to champion when its scores{' '}
          <span style={{ display: 'inline-flex', alignItems: 'center' }}>
            Pareto-dominate<InfoTooltip info={CONCEPT_INFO.pareto} size={11} />
          </span>{' '}
          the base on at least one benchmark without regressing others. Click Start Evolution
          to train your first generation.
        </p>
        <div style={{ paddingTop: 12, borderTop: `1px solid ${C.border}`, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button
            type="button"
            onClick={() => navigate('/dashboard?startEvolution=1')}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              padding: '6px 14px',
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
        </div>
      </div>
    );
  }

  // Rendered champion — caption, score bars, and a 4-button action strip.
  const adapterId = champion.adapter_id || '';
  const goPlayground = () =>
    navigate(adapterId ? `/playground?adapter=${encodeURIComponent(adapterId)}` : '/playground');
  const goCompare = () =>
    navigate(adapterId ? `/playground?compare=base-vs-${encodeURIComponent(adapterId)}` : '/playground');
  const goLineage = () =>
    navigate(adapterId ? `/lineage?node=${encodeURIComponent(adapterId)}` : '/lineage');
  const startNextGen = () => {
    window.dispatchEvent(
      new CustomEvent('mf:open-evolution-dialog', {
        detail: { existing_adapter: champion.adapter_path || '' },
      })
    );
  };

  const actionBtnStyle = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 5,
    padding: '5px 10px',
    background: 'transparent',
    color: C.txtS,
    border: `1px solid ${C.border}`,
    borderRadius: 4,
    cursor: 'pointer',
    fontFamily: F.ui,
    fontSize: 12,
  };
  const primaryBtnStyle = {
    ...actionBtnStyle,
    color: C.acc,
    border: `1px solid ${C.borderA}`,
    fontWeight: 500,
  };

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
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
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
          onClick={goPlayground}
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

      {/* Caption: Champion · Gen N · promoted {ago} · {model} */}
      <div
        style={{
          fontFamily: F.ui,
          fontSize: 11,
          color: C.txtM,
          marginBottom: 10,
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          gap: 4,
          lineHeight: 1.5,
        }}
      >
        <span style={{ display: 'inline-flex', alignItems: 'center' }}>
          Champion<InfoTooltip info={CONCEPT_INFO.champion} size={11} />
        </span>
        <span style={{ color: C.txtM }}>·</span>
        <span style={{ display: 'inline-flex', alignItems: 'center' }}>
          Gen {champion.generation}<InfoTooltip info={CONCEPT_INFO.generation} size={11} />
        </span>
        <span style={{ color: C.txtM }}>·</span>
        <span>promoted {relativeTime(champion.promoted_at)}</span>
        {champion.base_model ? (
          <>
            <span style={{ color: C.txtM }}>·</span>
            <span style={{ fontFamily: F.mono, color: C.txtS }}>{champion.base_model}</span>
          </>
        ) : null}
      </div>

      <div style={{ marginBottom: 12 }}>
        {champion.scores &&
          Object.entries(champion.scores).map(([bench, score]) => (
            <ScoreBar key={bench} label={bench} value={score} color={BENCH_COLORS[bench] || C.acc} />
          ))}
      </div>

      <div
        style={{
          paddingTop: 12,
          borderTop: `1px solid ${C.border}`,
          display: 'flex',
          gap: 6,
          flexWrap: 'wrap',
        }}
      >
        <button type="button" onClick={goPlayground} style={primaryBtnStyle} title="Run inference with this champion">
          <MessageSquare size={12} /> Test in Playground
        </button>
        <button type="button" onClick={goCompare} style={actionBtnStyle} title="Side-by-side base vs champion">
          <GitCompare size={12} /> Compare vs Base
        </button>
        <button type="button" onClick={startNextGen} style={actionBtnStyle} title="Start a new evolution from this champion">
          <Trophy size={12} /> Start Next Generation
        </button>
        <button type="button" onClick={goLineage} style={actionBtnStyle} title="View this champion in the lineage tree">
          <GitBranch size={12} /> View Lineage
        </button>
      </div>
    </div>
  );
}
