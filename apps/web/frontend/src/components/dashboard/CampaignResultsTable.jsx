import { useEffect, useState } from 'react';
import { apiFetch } from '../../config/api';
import { C, F } from '../../config/colors';

const STATUS_STYLES = {
  completed: { glyph: '✓', color: C.acc || '#22c55e' },
  running:   { glyph: '●', color: '#38bdf8' },
  failed:    { glyph: '✗', color: C.danger || '#ef4444' },
  pending:   { glyph: '○', color: C.txtM },
};

function shortModel(m) {
  if (!m) return '—';
  return String(m).split('/').slice(-1)[0] || m;
}

function fmtSecs(s) {
  if (s == null || !Number.isFinite(s)) return '—';
  s = Math.floor(s);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${s}s`;
}

function avgFromScores(scores) {
  if (!scores || typeof scores !== 'object') return null;
  const vals = Object.values(scores).filter((v) => typeof v === 'number');
  if (!vals.length) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

/**
 * Per-experiment results table — same data the /campaigns banner shows,
 * lifted onto /dashboard so a long campaign run is fully readable from the
 * landing page.
 *
 * Polls /api/campaigns/{plan_id}/results every 10s while a campaign is
 * active (`active=true`); stops polling once it goes idle so we don't
 * hammer the API forever.
 */
export default function CampaignResultsTable({ planId, experiments, active }) {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!planId) return undefined;
    let cancelled = false;
    const fetchOnce = async () => {
      try {
        const data = await apiFetch(`/api/campaigns/${planId}/results`);
        if (cancelled) return;
        setRows(Array.isArray(data?.results) ? data.results : []);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(e?.message || 'fetch failed');
      }
    };
    fetchOnce();
    if (!active) return () => { cancelled = true; };
    const iv = setInterval(fetchOnce, 10_000);
    return () => {
      cancelled = true;
      clearInterval(iv);
    };
  }, [planId, active]);

  // Merge: prefer DB rows when present, fall back to the campaign config so
  // the table renders all 6 rows immediately even before the first
  // experiment finishes.
  const merged = (experiments || []).map((exp, idx) => {
    const dbRow = rows.find((r) => r.experiment_index === idx);
    const status =
      dbRow?.status
      || (idx === 0 && active ? 'running' : 'pending');
    const avg = avgFromScores(dbRow?.scores);
    return {
      idx,
      model: exp.model || exp.base_model || dbRow?.config?.model || '—',
      method: exp.method || (exp.eval_only ? 'baseline' : 'sequential'),
      status,
      avg_score: avg,
      duration_seconds: dbRow?.duration_seconds,
      error: dbRow?.error,
    };
  });

  return (
    <div style={{ marginBottom: 16 }}>
      <div
        style={{
          fontFamily: F.ui,
          fontSize: 9,
          fontWeight: 700,
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          color: C.txtM,
          marginBottom: 8,
        }}
      >
        Per-experiment results {planId ? `· ${planId}` : ''}
      </div>
      {error ? (
        <div style={{ fontFamily: F.mono, fontSize: 11, color: C.danger || '#ef4444' }}>
          {error}
        </div>
      ) : null}
      <div
        style={{
          border: `1px solid ${C.border}`,
          borderRadius: 6,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '32px minmax(0, 2fr) 90px 80px 70px 80px',
            gap: 8,
            padding: '6px 12px',
            background: 'rgba(255,255,255,0.025)',
            borderBottom: `1px solid ${C.border}`,
            fontFamily: F.mono,
            fontSize: 9,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            color: C.txtM,
          }}
        >
          <span>#</span>
          <span>Model</span>
          <span>Method</span>
          <span>Status</span>
          <span style={{ textAlign: 'right' }}>Avg</span>
          <span style={{ textAlign: 'right' }}>Duration</span>
        </div>
        {merged.map((r) => {
          const sty = STATUS_STYLES[r.status] || STATUS_STYLES.pending;
          return (
            <div
              key={r.idx}
              style={{
                display: 'grid',
                gridTemplateColumns: '32px minmax(0, 2fr) 90px 80px 70px 80px',
                gap: 8,
                padding: '6px 12px',
                borderBottom: `1px solid ${C.border}`,
                fontFamily: F.mono,
                fontSize: 11,
                color: C.txtS,
                alignItems: 'center',
              }}
            >
              <span style={{ color: C.txtM }}>{r.idx + 1}</span>
              <span
                title={r.model}
                style={{
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  color: C.txtP,
                }}
              >
                {shortModel(r.model)}
              </span>
              <span style={{ color: C.txtM }}>{r.method}</span>
              <span style={{ color: sty.color, fontWeight: 700 }}>
                {sty.glyph} {r.status}
              </span>
              <span style={{ color: C.txtP, textAlign: 'right' }}>
                {r.avg_score != null ? r.avg_score.toFixed(3) : '—'}
              </span>
              <span style={{ color: C.txtM, textAlign: 'right' }}>
                {fmtSecs(r.duration_seconds)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
