import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  ArrowDownToLine,
  ChevronDown,
  ChevronRight,
  Compass,
  Crown,
  GitCompare,
  Layers,
  MessageSquare,
  Plus,
  RotateCcw,
  Server,
  Target,
  Trash2,
  X,
} from 'lucide-react';
import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
} from 'recharts';
import { BENCH_COLORS, C, F } from '../config/colors';
import {
  apiFetch,
  compareAdapters,
  deleteAdapter,
  fetchAdapters,
  rollbackAdapter,
  serveAdapter,
} from '../config/api';

const POLL_FAST_MS = 5000;
const POLL_SLOW_MS = 20000;
const BENCH_KEYS = ['mmlu', 'arc_challenge', 'hellaswag', 'gsm8k', 'humaneval'];
const BENCH_LABELS = {
  mmlu: 'MMLU',
  arc_challenge: 'ARC-C',
  hellaswag: 'HellaSwag',
  gsm8k: 'GSM8K',
  humaneval: 'HumanEval',
};

function avgOf(scores) {
  if (!scores || typeof scores !== 'object') return null;
  const v = Object.values(scores).filter((x) => typeof x === 'number');
  if (!v.length) return null;
  return v.reduce((a, b) => a + b, 0) / v.length;
}

function fmtBytes(mb) {
  if (mb == null) return '—';
  if (mb >= 1024) return `${(mb / 1024).toFixed(2)} GB`;
  return `${Number(mb).toFixed(1)} MB`;
}

function fmtRel(ts) {
  if (!ts) return '—';
  const t = new Date(ts).getTime();
  const dt = (Date.now() - t) / 1000;
  if (dt < 60) return `${Math.floor(dt)}s ago`;
  if (dt < 3600) return `${Math.floor(dt / 60)}m ago`;
  if (dt < 86400) return `${Math.floor(dt / 3600)}h ago`;
  return new Date(ts).toLocaleString();
}

function statusTone(row) {
  if (row.is_champion) return { fg: '#d4a574', bg: 'rgba(212,165,116,0.10)', border: 'rgba(212,165,116,0.45)', label: 'champion' };
  if (row.promoted) return { fg: C.acc, bg: 'rgba(118,185,0,0.08)', border: 'rgba(118,185,0,0.40)', label: 'promoted' };
  if (row.status === 'archived') return { fg: C.txtM, bg: 'rgba(100,116,139,0.10)', border: C.border, label: 'archived' };
  return { fg: C.ind, bg: 'rgba(129,140,248,0.08)', border: 'rgba(129,140,248,0.40)', label: row.status || '—' };
}

/** 5 thin per-benchmark bars used in the list rows + compare workspace. */
function MiniBars({ scores, height = 24, width = 14 }) {
  return (
    <div style={{ display: 'flex', gap: 3, alignItems: 'flex-end', height }}>
      {BENCH_KEYS.map((k) => {
        const v = typeof scores?.[k] === 'number' ? scores[k] : 0;
        const has = typeof scores?.[k] === 'number';
        const pct = Math.max(2, Math.min(100, v * 100));
        return (
          <div
            key={k}
            title={`${BENCH_LABELS[k]}: ${has ? v.toFixed(3) : '—'}`}
            style={{ width, height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', cursor: 'help' }}
          >
            <div style={{ height: `${pct}%`, background: BENCH_COLORS[k] || '#94a3b8', borderRadius: 2, opacity: has ? 0.85 : 0.18 }} />
          </div>
        );
      })}
    </div>
  );
}

function downloadAdapterReport(row) {
  const report = {
    adapter_id: row.adapter_id,
    run_id: row.run_id,
    generation: row.generation,
    base_model: row.base_model,
    is_champion: row.is_champion,
    promoted: row.promoted,
    status: row.status,
    avg_score: avgOf(row.scores),
    scores: row.scores,
    weak_categories: row.weak_categories,
    training_config: row.training_config,
    adapter_path: row.adapter_path,
    size_mb: row.size_mb,
    created_at: row.created_at,
  };
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const safe = String(row.adapter_id || 'adapter').replace(/[^a-zA-Z0-9._-]/g, '_');
  a.href = url;
  a.download = `${safe}-report.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function FilterPill({ label, count, active, color, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '4px 10px',
        background: active ? `${color}22` : 'transparent',
        border: `1px solid ${active ? color : C.border}`,
        borderRadius: 999,
        color: active ? color : C.txtS,
        fontFamily: F.ui,
        fontSize: 11,
        fontWeight: 600,
        cursor: 'pointer',
        textTransform: 'capitalize',
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: 999, background: color }} />
      {label}
      <span style={{ color: C.txtM, fontFamily: F.mono, fontSize: 10 }}>{count}</span>
    </button>
  );
}

function ActionButton({ icon: Icon, label, onClick, variant = 'ghost', danger, disabled, title }) {
  const palette = danger
    ? { bg: 'rgba(239,68,68,0.06)', border: `${C.danger}55`, fg: C.danger }
    : variant === 'primary'
      ? { bg: C.acc, border: C.acc, fg: '#0a0e16' }
      : { bg: 'transparent', border: C.border, fg: C.txtS };
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title || label}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '7px 12px',
        background: palette.bg,
        color: palette.fg,
        border: `1px solid ${palette.border}`,
        borderRadius: 6,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.4 : 1,
        fontFamily: F.ui,
        fontSize: 12,
        fontWeight: 600,
        // Critical: ensure clicks aren't intercepted by hover-overlay siblings.
        position: 'relative',
        zIndex: 2,
      }}
    >
      <Icon size={13} />
      {label}
    </button>
  );
}

function PromoteToTrackControl({ adapterId, disabled, onPromoted }) {
  const [tracks, setTracks] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState('');

  useEffect(() => {
    if (!open || tracks.length > 0) return;
    setLoading(true);
    apiFetch('/api/forge/tracks')
      .then((r) => setTracks(r?.tracks || []))
      .finally(() => setLoading(false));
  }, [open, tracks.length]);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (!e.target.closest('[data-promote-track-popover]')) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  async function promote(track) {
    setBusy(track.track_id);
    try {
      const r = await apiFetch(`/api/adapters/${adapterId}/promote_to_track`, {
        method: 'POST',
        body: JSON.stringify({ track_id: track.track_id }),
      });
      onPromoted?.(track, r);
      setOpen(false);
    } catch (e) {
      alert(`Promote failed: ${e?.message || 'unknown'}`);
    } finally {
      setBusy('');
    }
  }

  return (
    <div data-promote-track-popover style={{ position: 'relative' }}>
      <ActionButton
        icon={Compass}
        label="Promote to track"
        onClick={() => setOpen(!open)}
        disabled={disabled}
      />
      {open ? (
        <div style={{
          position: 'absolute', top: 'calc(100% + 4px)', left: 0,
          background: C.bgC, border: `1px solid ${C.border}`,
          borderRadius: 6, padding: 4, minWidth: 240, zIndex: 100,
          boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
        }}>
          {loading ? (
            <div style={{ padding: 10, fontFamily: F.ui, fontSize: 11, color: C.txtM, textAlign: 'center' }}>
              Loading tracks…
            </div>
          ) : tracks.filter((t) => t.enabled).length === 0 ? (
            <div style={{ padding: 10, fontFamily: F.ui, fontSize: 11, color: C.txtM, textAlign: 'center' }}>
              No enabled tracks.
            </div>
          ) : (
            tracks.filter((t) => t.enabled).map((t) => (
              <button
                key={t.track_id}
                type="button"
                onClick={() => promote(t)}
                disabled={!!busy}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  width: '100%', textAlign: 'left',
                  padding: '7px 10px', borderRadius: 4,
                  background: 'transparent', border: 'none', cursor: busy ? 'wait' : 'pointer',
                  opacity: busy === t.track_id ? 0.5 : 1,
                }}
                onMouseEnter={(e) => { if (!busy) e.currentTarget.style.background = C.bgI; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
              >
                <Target size={12} color={C.acc} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: F.ui, fontSize: 12, color: C.txtP, fontWeight: 600 }}>
                    {t.name}
                  </div>
                  <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM }}>
                    {t.track_id} · {(t.target_benchmarks || []).join(', ')}
                  </div>
                </div>
                {t.has_adapter ? (
                  <span style={{ fontFamily: F.mono, fontSize: 9, color: C.acc, padding: '1px 5px', borderRadius: 999, background: C.accDim, border: `1px solid ${C.borderA}` }}>
                    has adapter
                  </span>
                ) : null}
              </button>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}

function AdapterRow({ row, selected, onSelect, onAddCompare, expanded, onToggleExpand }) {
  const tone = statusTone(row);
  const avg = avgOf(row.scores);
  const noWeights = row.has_weights === false;
  return (
    <Fragment>
      <div
        // No mf-card-hover here on purpose — the previous Adapters page used it
        // and the hover overlay intercepted clicks on the row's action buttons.
        onClick={() => onSelect(row)}
        style={{
          display: 'grid',
          gridTemplateColumns: '24px 70px minmax(0,1fr) 110px 70px auto',
          gap: 10,
          alignItems: 'center',
          padding: '10px 12px',
          background: selected ? 'rgba(118,185,0,0.05)' : 'transparent',
          borderLeft: `3px solid ${selected ? tone.fg : 'transparent'}`,
          borderBottom: `1px solid ${C.border}`,
          cursor: 'pointer',
          opacity: row.status === 'archived' ? 0.7 : 1,
          transition: 'background 200ms, border-color 200ms',
        }}
      >
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onToggleExpand(row.adapter_id); }}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: C.txtM, padding: 0, display: 'flex' }}
          title={expanded ? 'Hide per-bench scores' : 'Show per-bench scores'}
        >
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>

        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            padding: '2px 7px',
            borderRadius: 999,
            fontSize: 10,
            fontFamily: F.ui,
            fontWeight: 700,
            background: tone.bg,
            color: tone.fg,
            border: `1px solid ${tone.border}`,
            textTransform: 'uppercase',
            letterSpacing: '0.04em',
            width: 'fit-content',
            whiteSpace: 'nowrap',
          }}
        >
          {row.is_champion ? <Crown size={10} /> : <span style={{ width: 6, height: 6, borderRadius: 999, background: tone.fg }} />}
          {tone.label}
        </span>

        <div style={{ minWidth: 0 }}>
          <div style={{ fontFamily: F.mono, fontSize: 12, color: C.txtP, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {row.run_id}<span style={{ color: C.txtM }}> · gen {row.generation}</span>
            {noWeights ? (
              <span style={{ marginLeft: 8, padding: '0 6px', fontSize: 9, fontFamily: F.ui, color: C.danger, border: `1px solid ${C.danger}55`, borderRadius: 999 }}>
                no weights
              </span>
            ) : null}
          </div>
          <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {row.base_model} · {fmtBytes(row.size_mb)} · {fmtRel(row.created_at)}
          </div>
        </div>

        <MiniBars scores={row.scores} />

        <span style={{ fontFamily: F.mono, fontSize: 14, color: avg != null ? tone.fg : C.txtM, textAlign: 'right' }}>
          {avg != null ? avg.toFixed(3) : '—'}
        </span>

        <div style={{ display: 'flex', gap: 4 }}>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onAddCompare(row); }}
            disabled={noWeights}
            title="Add to compare workspace"
            style={{
              padding: '5px 8px',
              background: 'transparent',
              border: `1px solid ${C.border}`,
              borderRadius: 6,
              color: noWeights ? C.txtM : C.txtS,
              cursor: noWeights ? 'not-allowed' : 'pointer',
              fontFamily: F.ui,
              fontSize: 11,
              fontWeight: 600,
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              position: 'relative',
              zIndex: 2,
            }}
          >
            <Plus size={11} /> Compare
          </button>
        </div>
      </div>
      {expanded ? (
        <div style={{ padding: '8px 12px 12px 50px', background: 'rgba(255,255,255,0.015)', borderBottom: `1px solid ${C.border}`, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {BENCH_KEYS.map((k) => {
            const v = row.scores?.[k];
            return (
              <div
                key={k}
                style={{
                  padding: '6px 10px',
                  background: C.bgI,
                  border: `1px solid ${C.border}`,
                  borderRadius: 6,
                  fontFamily: F.mono,
                  fontSize: 11,
                  color: typeof v === 'number' ? C.txtP : C.txtM,
                }}
              >
                <span style={{ color: BENCH_COLORS[k] || C.txtS }}>{BENCH_LABELS[k]}</span>{' '}
                {typeof v === 'number' ? v.toFixed(3) : '—'}
              </div>
            );
          })}
        </div>
      ) : null}
    </Fragment>
  );
}

function DetailPane({ row, lineageRow, onServe, onMakeChampion, onDelete, onAddCompare, busy }) {
  if (!row) {
    return (
      <div style={{ padding: 24, fontFamily: F.ui, fontSize: 13, color: C.txtM }}>
        Select an adapter to inspect its scores, training config, and actions.
      </div>
    );
  }
  const tone = statusTone(row);
  const avg = avgOf(row.scores);
  const noWeights = row.has_weights === false;

  // Merge in lineage-row data (decision_reason, training_data_size, duration)
  // when available — the adapters route returns these fields empty for older
  // generations that were stored before the runner persisted full config.
  const decisionReason = row.decision_reason || lineageRow?.decision_reason;
  const trainingDataSize = row.training_data_size ?? lineageRow?.training_data_size;
  const durationS = row.duration_seconds ?? lineageRow?.duration_seconds;
  const cfg = (row.training_config && Object.keys(row.training_config).length)
    ? row.training_config
    : (lineageRow?.config || lineageRow?.data?.config || {});

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflowY: 'auto' }}>
      <div style={{ padding: '16px 18px 12px', borderBottom: `1px solid ${C.border}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          {row.is_champion ? <Crown size={14} color={tone.fg} /> : null}
          <span
            style={{
              padding: '2px 9px',
              borderRadius: 999,
              fontFamily: F.ui,
              fontSize: 10,
              fontWeight: 700,
              background: tone.bg,
              color: tone.fg,
              border: `1px solid ${tone.border}`,
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
            }}
          >
            {tone.label}
          </span>
          <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM, marginLeft: 'auto' }}>
            gen {row.generation}
          </span>
        </div>
        <div style={{ fontFamily: F.mono, fontSize: 14, color: C.txtP, fontWeight: 500, wordBreak: 'break-all' }}>
          {row.adapter_id}
        </div>
        <div style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM, marginTop: 4 }}>
          {row.base_model}
        </div>
      </div>

      <div style={{ padding: '14px 18px', borderBottom: `1px solid ${C.border}` }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 10 }}>
          <div>
            <div style={{ fontFamily: F.mono, fontSize: 9, color: C.txtM, letterSpacing: '0.08em', textTransform: 'uppercase' }}>Avg score</div>
            <div style={{ fontFamily: F.mono, fontSize: 26, color: tone.fg, lineHeight: 1.1 }}>
              {avg != null ? avg.toFixed(3) : '—'}
            </div>
          </div>
          <div style={{ marginLeft: 'auto' }}>
            <div style={{ fontFamily: F.mono, fontSize: 9, color: C.txtM, letterSpacing: '0.08em', textTransform: 'uppercase' }}>Size</div>
            <div style={{ fontFamily: F.mono, fontSize: 12, color: C.txtS }}>{fmtBytes(row.size_mb)}</div>
          </div>
          <div>
            <div style={{ fontFamily: F.mono, fontSize: 9, color: C.txtM, letterSpacing: '0.08em', textTransform: 'uppercase' }}>Created</div>
            <div style={{ fontFamily: F.mono, fontSize: 12, color: C.txtS }}>{fmtRel(row.created_at)}</div>
          </div>
        </div>
        {/* Per-benchmark breakdown with bars */}
        {BENCH_KEYS.map((k) => {
          const v = row.scores?.[k];
          const pct = typeof v === 'number' ? Math.max(0, Math.min(100, v * 100)) : 0;
          return (
            <div key={k} style={{ marginBottom: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span style={{ fontFamily: F.mono, fontSize: 11, color: BENCH_COLORS[k] || C.txtS }}>{BENCH_LABELS[k]}</span>
                <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtP }}>
                  {typeof v === 'number' ? v.toFixed(3) : '—'}
                </span>
              </div>
              <div style={{ height: 4, background: 'rgba(255,255,255,0.05)', borderRadius: 999, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${pct}%`, background: BENCH_COLORS[k] || '#94a3b8', borderRadius: 999 }} />
              </div>
            </div>
          );
        })}
      </div>

      {/* Decision + lineage extras */}
      {(decisionReason || trainingDataSize || durationS) ? (
        <div style={{ padding: '14px 18px', borderBottom: `1px solid ${C.border}`, fontFamily: F.ui, fontSize: 12, color: C.txtS, lineHeight: 1.5 }}>
          {decisionReason ? (
            <div style={{ marginBottom: 6 }}>
              <span style={{ color: C.txtM, fontFamily: F.mono, fontSize: 10, marginRight: 6 }}>DECISION</span>
              {decisionReason}
            </div>
          ) : null}
          <div style={{ display: 'flex', gap: 14, fontFamily: F.mono, fontSize: 11, color: C.txtM }}>
            {trainingDataSize != null ? <span><span style={{ color: C.txtS }}>{Number(trainingDataSize).toLocaleString()}</span> samples</span> : null}
            {durationS != null ? <span><span style={{ color: C.txtS }}>{Math.round(durationS / 60)}</span> min total</span> : null}
            {row.weak_categories?.length ? (
              <span><span style={{ color: C.txtS }}>{row.weak_categories.length}</span> categories</span>
            ) : null}
          </div>
        </div>
      ) : null}

      {/* Training config */}
      <div style={{ padding: '14px 18px', borderBottom: `1px solid ${C.border}` }}>
        <div style={{ fontFamily: F.mono, fontSize: 9, color: C.txtM, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>
          Training config
        </div>
        {Object.keys(cfg).length === 0 ? (
          <div style={{ fontFamily: F.ui, fontSize: 11, color: C.txtM, lineHeight: 1.4 }}>
            Not recorded for this run. Newer runs persist lora_rank, lora_alpha, learning_rate, batch_size, base_model and max_samples here.
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 6 }}>
            {Object.entries(cfg).filter(([k]) => k !== 'run_id').map(([k, v]) => (
              <div
                key={k}
                style={{
                  padding: '6px 9px',
                  background: C.bgI,
                  border: `1px solid ${C.border}`,
                  borderRadius: 6,
                  fontFamily: F.mono,
                  fontSize: 11,
                }}
              >
                <div style={{ color: C.txtM, fontSize: 9, letterSpacing: '0.06em', textTransform: 'uppercase' }}>{k}</div>
                <div style={{ color: C.txtP, marginTop: 1, wordBreak: 'break-all' }}>
                  {v == null || v === '' ? '—' : Array.isArray(v) ? v.join(', ') : String(v)}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Adapter path */}
      <div style={{ padding: '12px 18px', borderBottom: `1px solid ${C.border}` }}>
        <div style={{ fontFamily: F.mono, fontSize: 9, color: C.txtM, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 4 }}>
          Adapter path
        </div>
        <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtS, wordBreak: 'break-all' }}>
          {row.adapter_path || '—'}
        </div>
      </div>

      {/* Actions */}
      <div style={{ padding: '14px 18px', display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 'auto' }}>
        <Link
          to="/playground"
          style={{ textDecoration: 'none' }}
        >
          <ActionButton icon={MessageSquare} label="Open in Playground" />
        </Link>
        <ActionButton
          icon={Server}
          label="Serve"
          onClick={() => onServe(row.adapter_id)}
          disabled={noWeights || busy === `${row.adapter_id}:serve`}
        />
        <ActionButton
          icon={Crown}
          label={row.is_champion ? 'Already champion' : 'Make Champion'}
          onClick={() => onMakeChampion(row.adapter_id)}
          variant="primary"
          disabled={row.is_champion || noWeights || busy === `${row.adapter_id}:rb`}
        />
        <ActionButton icon={GitCompare} label="Add to Compare" onClick={() => onAddCompare(row)} disabled={noWeights} />
        <PromoteToTrackControl
          adapterId={row.adapter_id}
          disabled={noWeights}
          onPromoted={(track) => {
            // Lightweight in-place feedback. AdaptersPage doesn't reload tracks
            // since it doesn't display them; the user navigates to /forge to see
            // the promotion take effect.
            // eslint-disable-next-line no-console
            console.log('[adapters] promoted', row.adapter_id, '→ track', track.track_id);
          }}
        />
        <ActionButton icon={ArrowDownToLine} label="Report" onClick={() => downloadAdapterReport(row)} />
        <ActionButton
          icon={Trash2}
          label="Delete"
          danger
          disabled={row.is_champion || busy === `${row.adapter_id}:del`}
          onClick={() => onDelete(row.adapter_id)}
        />
      </div>
    </div>
  );
}

function CompareWorkspace({ slotA, slotB, onClear, prompt, onPrompt, onRun, busy, result, lineageById }) {
  // Build the radar dataset only once both slots are populated.
  const radarData = useMemo(() => {
    if (!slotA || !slotB) return [];
    const a = slotA.scores || {};
    const b = slotB.scores || {};
    const keys = new Set([...BENCH_KEYS, ...Object.keys(a), ...Object.keys(b)]);
    return Array.from(keys).map((k) => ({
      bench: BENCH_LABELS[k] || k,
      a: typeof a[k] === 'number' ? a[k] : 0,
      b: typeof b[k] === 'number' ? b[k] : 0,
    }));
  }, [slotA, slotB]);

  const Slot = ({ label, row, color, onRemove }) => (
    <div
      style={{
        flex: 1,
        minWidth: 240,
        padding: 12,
        background: 'rgba(255,255,255,0.02)',
        border: `1px dashed ${row ? color : C.border}`,
        borderRadius: 8,
        minHeight: 92,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <span style={{ fontFamily: F.mono, fontSize: 10, color: row ? color : C.txtM, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          Slot {label}
        </span>
        {row ? (
          <button
            type="button"
            onClick={onRemove}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: C.txtM, padding: 2 }}
            title="Remove from compare"
          >
            <X size={12} />
          </button>
        ) : null}
      </div>
      {row ? (
        <>
          <div style={{ fontFamily: F.mono, fontSize: 12, color: C.txtP, wordBreak: 'break-all' }}>{row.adapter_id}</div>
          <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, marginTop: 4 }}>{row.base_model}</div>
          <div style={{ marginTop: 8 }}>
            <MiniBars scores={row.scores} height={22} />
          </div>
          <div style={{ marginTop: 6, fontFamily: F.mono, fontSize: 11, color }}>
            avg {avgOf(row.scores)?.toFixed(3) ?? '—'}
          </div>
        </>
      ) : (
        <div style={{ fontFamily: F.ui, fontSize: 12, color: C.txtM, lineHeight: 1.5 }}>
          Click <span style={{ color: C.txtS, fontFamily: F.mono }}>+ Compare</span> on any adapter row, or use the detail-pane action.
        </div>
      )}
    </div>
  );

  // Inference-comparison panes (rendered after Run on a prompt).
  const renderResult = () => {
    if (!result) return null;
    const ra = result.inference_a;
    const rb = result.inference_b;
    return (
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12 }}>
        {[['A', ra, C.ind], ['B', rb, C.acc]].map(([key, r, color]) => (
          <div key={key} style={{ padding: 12, background: '#111827', border: `1px solid ${color}33`, borderRadius: 8 }}>
            <div style={{ fontFamily: F.mono, fontSize: 10, color, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 6 }}>
              {key} · {r?.adapter_id || '—'}
            </div>
            <div style={{ fontFamily: F.ui, fontSize: 12, color: C.txtP, lineHeight: 1.55, whiteSpace: 'pre-wrap', maxHeight: 240, overflowY: 'auto' }}>
              {r?.response || r?.error || '—'}
            </div>
          </div>
        ))}
      </div>
    );
  };

  return (
    <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10, gap: 12, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <GitCompare size={14} color={C.acc} />
          <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: C.txtM }}>
            Compare workspace
          </span>
        </div>
        <button
          type="button"
          onClick={onClear}
          disabled={!slotA && !slotB}
          style={{
            padding: '4px 10px',
            background: 'transparent',
            border: `1px solid ${C.border}`,
            borderRadius: 6,
            color: (!slotA && !slotB) ? C.txtM : C.txtS,
            cursor: (!slotA && !slotB) ? 'not-allowed' : 'pointer',
            fontFamily: F.ui,
            fontSize: 11,
          }}
        >
          Clear
        </button>
      </div>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <Slot label="A" row={slotA} color={C.ind} onRemove={() => onClear('a')} />
        <Slot label="B" row={slotB} color={C.acc} onRemove={() => onClear('b')} />
      </div>

      {slotA && slotB ? (
        <>
          {/* Per-bench delta strip */}
          <div style={{ marginTop: 14, padding: 12, background: C.bgI, border: `1px solid ${C.border}`, borderRadius: 8 }}>
            <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>
              Per-benchmark delta (B − A)
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 8 }}>
              {BENCH_KEYS.map((k) => {
                const a = typeof slotA.scores?.[k] === 'number' ? slotA.scores[k] : null;
                const b = typeof slotB.scores?.[k] === 'number' ? slotB.scores[k] : null;
                const delta = a != null && b != null ? b - a : null;
                const tone = delta == null ? C.txtM : delta > 0.001 ? C.success : delta < -0.001 ? C.danger : C.txtM;
                return (
                  <div key={k} style={{ padding: '6px 10px', background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 6 }}>
                    <div style={{ fontFamily: F.mono, fontSize: 10, color: BENCH_COLORS[k] || C.txtS }}>{BENCH_LABELS[k]}</div>
                    <div style={{ fontFamily: F.mono, fontSize: 13, color: tone, fontWeight: 600 }}>
                      {delta == null ? '—' : `${delta > 0 ? '+' : ''}${delta.toFixed(3)}`}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Radar overlay */}
          <div style={{ marginTop: 14, height: 280 }}>
            <ResponsiveContainer>
              <RadarChart data={radarData} outerRadius={100}>
                <PolarGrid stroke={C.border} />
                <PolarAngleAxis dataKey="bench" tick={{ fill: C.txtS, fontSize: 11 }} />
                <PolarRadiusAxis angle={30} domain={[0, 1]} tick={{ fill: C.txtM, fontSize: 9 }} />
                <Radar name="A" dataKey="a" stroke={C.ind} fill={C.ind} fillOpacity={0.25} />
                <Radar name="B" dataKey="b" stroke={C.acc} fill={C.acc} fillOpacity={0.25} />
              </RadarChart>
            </ResponsiveContainer>
          </div>

          {/* Inference compare on a prompt */}
          <div style={{ marginTop: 12 }}>
            <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 6 }}>
              Same-prompt inference
            </div>
            <textarea
              value={prompt}
              onChange={(e) => onPrompt(e.target.value)}
              rows={2}
              placeholder="Prompt for both adapters…"
              style={{
                width: '100%',
                background: C.bgI,
                border: `1px solid ${C.border}`,
                borderRadius: 6,
                color: C.txtP,
                padding: 10,
                fontFamily: F.mono,
                fontSize: 12,
                resize: 'vertical',
              }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
              <ActionButton
                icon={GitCompare}
                label={busy === 'compare' ? 'Running…' : 'Run on both'}
                variant="primary"
                onClick={onRun}
                disabled={!prompt.trim() || busy === 'compare'}
              />
            </div>
            {renderResult()}
          </div>
        </>
      ) : null}
    </div>
  );
}

export default function AdaptersPage() {
  const [data, setData] = useState(null);
  const [lineage, setLineage] = useState([]);
  const [evolve, setEvolve] = useState(null);
  const [err, setErr] = useState(null);
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [showArchived, setShowArchived] = useState(false);
  const [expanded, setExpanded] = useState({});
  const [selected, setSelected] = useState(null);
  const [slotA, setSlotA] = useState(null);
  const [slotB, setSlotB] = useState(null);
  const [cmpPrompt, setCmpPrompt] = useState('Summarize the benefits of unit tests in 2 sentences.');
  const [cmpResult, setCmpResult] = useState(null);
  const [busy, setBusy] = useState('');
  const [searchParams, setSearchParams] = useSearchParams();

  const load = useCallback(async () => {
    try {
      const [a, l, ev] = await Promise.all([
        fetchAdapters().catch((e) => { throw e; }),
        apiFetch('/api/lineage/generations').catch(() => []),
        apiFetch('/api/evolve/status').catch(() => null),
      ]);
      setData(a);
      setLineage(Array.isArray(l) ? l : []);
      setEvolve(ev);
      setErr(null);
    } catch (e) {
      setData({ adapters: [], total: 0, champion_id: null, total_disk_mb: 0 });
      const st = e?.status;
      setErr(st === 401 || st === 403
        ? 'API key missing or invalid — check Settings.'
        : 'Could not load adapters.');
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Adaptive polling: 5s while a run is active, 20s when idle.
  useEffect(() => {
    const fast = evolve?.is_running === true || evolve?.status === 'running';
    const ms = fast ? POLL_FAST_MS : POLL_SLOW_MS;
    const iv = setInterval(load, ms);
    return () => clearInterval(iv);
  }, [evolve?.is_running, evolve?.status, load]);

  const rows = data?.adapters || [];
  // Sort: champion → promoted → other → archived; newest gen first within each
  const sortedRows = useMemo(() => {
    const order = (a) => (a.is_champion ? 0 : a.promoted ? 1 : a.status === 'archived' ? 3 : 2);
    return [...rows].sort((a, b) => {
      const o = order(a) - order(b);
      if (o !== 0) return o;
      return new Date(b.created_at || 0) - new Date(a.created_at || 0);
    });
  }, [rows]);

  const counts = useMemo(() => {
    const c = { all: rows.length, champion: 0, promoted: 0, archived: 0 };
    for (const r of rows) {
      if (r.is_champion) c.champion += 1;
      else if (r.promoted) c.promoted += 1;
      else if (r.status === 'archived') c.archived += 1;
    }
    return c;
  }, [rows]);

  const visibleRows = useMemo(() => {
    let out = sortedRows;
    if (filter === 'champion') out = out.filter((r) => r.is_champion);
    else if (filter === 'promoted') out = out.filter((r) => r.promoted && !r.is_champion);
    else if (filter === 'archived') out = out.filter((r) => r.status === 'archived');
    else if (!showArchived && counts.archived > 5) {
      out = out.filter((r) => r.status !== 'archived');
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      out = out.filter(
        (r) =>
          (r.adapter_id || '').toLowerCase().includes(q) ||
          (r.run_id || '').toLowerCase().includes(q) ||
          (r.base_model || '').toLowerCase().includes(q),
      );
    }
    return out;
  }, [sortedRows, filter, search, showArchived, counts.archived]);

  // Default selection = champion when none chosen (matches Lineage UX).
  useEffect(() => {
    if (selected || !rows.length) return;
    const champ = rows.find((r) => r.is_champion) || rows[0];
    setSelected(champ);
  }, [rows, selected]);

  // Deep-link from Lineage (or anywhere) to pre-fill compare slots.
  useEffect(() => {
    const a = searchParams.get('compare_a');
    const b = searchParams.get('compare_b');
    if (!a && !b) return;
    if (!rows.length) return;
    const findOne = (key) => {
      if (!key) return null;
      // The lineage page passes ids in the form "<run>-gen-<n>"; the adapters
      // route returns "<run>__gen<n>". Normalise both to a comparable shape.
      const norm = (s) => String(s || '').replace('__gen', '-gen-').replace(/_+/g, '_');
      return rows.find((r) => r.adapter_id === key || norm(r.adapter_id) === norm(key)) || null;
    };
    const a1 = findOne(a);
    const b1 = findOne(b);
    if (a1) setSlotA(a1);
    if (b1) setSlotB(b1);
    // Clean the URL so reloads don't keep refilling.
    if (a1 || b1) {
      const next = new URLSearchParams(searchParams);
      next.delete('compare_a');
      next.delete('compare_b');
      setSearchParams(next, { replace: true });
    }
  }, [rows, searchParams, setSearchParams]);

  const lineageById = useMemo(() => {
    const map = {};
    for (const row of lineage) {
      const key = `${row.run_id}__gen${row.generation}`;
      map[key] = row;
    }
    return map;
  }, [lineage]);

  function addToCompare(row) {
    if (!slotA) setSlotA(row);
    else if (!slotB && slotA.adapter_id !== row.adapter_id) setSlotB(row);
    else setSlotB(row); // replace B if both filled
  }

  function clearCompare(which) {
    setCmpResult(null);
    if (which === 'a') setSlotA(null);
    else if (which === 'b') setSlotB(null);
    else { setSlotA(null); setSlotB(null); }
  }

  async function runCompare() {
    if (!slotA || !slotB || !cmpPrompt.trim()) return;
    setBusy('compare');
    setCmpResult(null);
    try {
      const r = await compareAdapters(slotA.adapter_id, slotB.adapter_id, cmpPrompt.trim());
      setCmpResult(r);
    } catch (e) {
      setCmpResult({
        inference_a: { adapter_id: slotA.adapter_id, error: e?.message || 'Failed' },
        inference_b: { adapter_id: slotB.adapter_id, error: e?.message || 'Failed' },
      });
    } finally {
      setBusy('');
    }
  }

  async function onServe(id) {
    setBusy(`${id}:serve`);
    try { await serveAdapter(id); await load(); } finally { setBusy(''); }
  }
  async function onMakeChampion(id) {
    if (!window.confirm(`Promote ${id} to champion?`)) return;
    setBusy(`${id}:rb`);
    try { await rollbackAdapter(id); await load(); } finally { setBusy(''); }
  }
  async function onDelete(id) {
    if (!window.confirm(`Delete ${id}? This removes the adapter weights from disk.`)) return;
    setBusy(`${id}:del`);
    try {
      await deleteAdapter(id);
      if (selected?.adapter_id === id) setSelected(null);
      await load();
    } finally {
      setBusy('');
    }
  }
  async function onCleanupArchived() {
    const archived = rows.filter((r) => r.status === 'archived' && !r.is_champion);
    if (!archived.length) return;
    if (!window.confirm(`Delete ${archived.length} archived adapter${archived.length === 1 ? '' : 's'}? This cannot be undone.`)) return;
    setBusy('cleanup');
    try {
      for (const a of archived) {
        try { await deleteAdapter(a.adapter_id); } catch { /* keep going */ }
      }
      await load();
    } finally {
      setBusy('');
    }
  }

  const isLive = evolve?.is_running === true || evolve?.status === 'running';
  const selectedLineage = selected ? lineageById[selected.adapter_id] : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, padding: '8px 0 40px', maxWidth: 1500, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Layers size={22} color={C.acc} />
        <div style={{ flex: 1 }}>
          <h1 style={{ fontFamily: F.display, fontSize: 26, color: C.txtP, margin: 0 }}>Adapters</h1>
          <p style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM, margin: '4px 0 0' }}>
            LoRA checkpoints — promote, serve, compare on the same prompt
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: F.mono, fontSize: 11, color: C.txtM }}>
          <span
            style={{
              width: 7, height: 7, borderRadius: 999,
              background: isLive ? C.acc : C.txtM,
              boxShadow: isLive ? `0 0 8px ${C.acc}` : 'none',
              animation: isLive ? 'mf-topbar-pulse 1.4s ease-out infinite' : 'none',
            }}
            aria-hidden
          />
          {isLive ? `LIVE · gen ${evolve?.generation ?? '?'} · ${evolve?.current_step || ''}` : 'idle'}
        </div>
      </div>

      {err && (
        <div style={{ padding: '10px 14px', background: C.warningDim, border: `1px solid ${C.warning}`, borderRadius: 8, color: C.warning, fontFamily: F.mono, fontSize: 12 }}>
          {err}
        </div>
      )}

      {/* Top strip: stats + filters + search + cleanup */}
      <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 12, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10 }}>
        <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM, marginRight: 4 }}>
          <span style={{ color: C.txtS }}>{counts.all}</span> total ·
          <span style={{ color: '#d4a574', marginLeft: 4 }}>{counts.champion}</span> champion ·
          <span style={{ color: C.acc, marginLeft: 4 }}>{counts.promoted}</span> promoted ·
          <span style={{ color: C.txtM, marginLeft: 4 }}>{counts.archived}</span> archived ·
          <span style={{ color: C.txtS, marginLeft: 4 }}>{((data?.total_disk_mb || 0) / 1024).toFixed(2)} GB</span> on disk
        </span>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <FilterPill label="all" count={counts.all} color={C.txtS} active={filter === 'all'} onClick={() => setFilter('all')} />
          <FilterPill label="champion" count={counts.champion} color="#d4a574" active={filter === 'champion'} onClick={() => setFilter('champion')} />
          <FilterPill label="promoted" count={counts.promoted} color={C.acc} active={filter === 'promoted'} onClick={() => setFilter('promoted')} />
          <FilterPill label="archived" count={counts.archived} color={C.txtM} active={filter === 'archived'} onClick={() => setFilter('archived')} />
        </div>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="filter by run / model"
          style={{
            flex: 1,
            minWidth: 140,
            padding: '6px 10px',
            background: C.bgI,
            border: `1px solid ${C.border}`,
            borderRadius: 6,
            color: C.txtP,
            fontFamily: F.mono,
            fontSize: 12,
          }}
        />
        {filter === 'all' && counts.archived > 5 ? (
          <button
            type="button"
            onClick={() => setShowArchived((v) => !v)}
            style={{
              padding: '6px 10px',
              background: 'transparent',
              border: `1px solid ${C.border}`,
              borderRadius: 6,
              color: C.txtS,
              cursor: 'pointer',
              fontFamily: F.ui,
              fontSize: 11,
            }}
            title="By default, archived adapters are hidden when there are more than 5"
          >
            {showArchived ? `Hide ${counts.archived} archived` : `Show ${counts.archived} archived`}
          </button>
        ) : null}
        {counts.archived > 0 ? (
          <button
            type="button"
            onClick={onCleanupArchived}
            disabled={busy === 'cleanup'}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 12px',
              background: busy === 'cleanup' ? C.bgE : 'transparent',
              border: `1px solid ${C.danger}55`,
              borderRadius: 6,
              color: C.danger,
              cursor: busy === 'cleanup' ? 'not-allowed' : 'pointer',
              fontFamily: F.ui,
              fontSize: 11,
              fontWeight: 600,
            }}
          >
            <Trash2 size={11} /> {busy === 'cleanup' ? 'Cleaning…' : `Clean up ${counts.archived}`}
          </button>
        ) : null}
      </div>

      {/* Master/detail body */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 6fr) minmax(320px, 4fr)', gap: 14, alignItems: 'stretch' }}>
        <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, overflow: 'hidden' }}>
          {/* Column header */}
          <div style={{ display: 'grid', gridTemplateColumns: '24px 70px minmax(0,1fr) 110px 70px auto', gap: 10, padding: '8px 12px', borderBottom: `1px solid ${C.border}`, background: 'rgba(255,255,255,0.02)' }}>
            <span />
            <span style={{ fontFamily: F.mono, fontSize: 9, color: C.txtM, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Status</span>
            <span style={{ fontFamily: F.mono, fontSize: 9, color: C.txtM, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Adapter</span>
            <span style={{ fontFamily: F.mono, fontSize: 9, color: C.txtM, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Per-bench</span>
            <span style={{ fontFamily: F.mono, fontSize: 9, color: C.txtM, letterSpacing: '0.06em', textTransform: 'uppercase', textAlign: 'right' }}>Avg</span>
            <span />
          </div>
          {visibleRows.length === 0 ? (
            <div style={{ padding: 24, textAlign: 'center', color: C.txtM, fontFamily: F.ui, fontSize: 13 }}>
              {filter === 'all' ? 'No adapters match this filter.' : `No ${filter} adapters.`}
            </div>
          ) : (
            visibleRows.map((row) => (
              <AdapterRow
                key={row.adapter_id}
                row={row}
                selected={selected?.adapter_id === row.adapter_id}
                onSelect={setSelected}
                onAddCompare={addToCompare}
                expanded={!!expanded[row.adapter_id]}
                onToggleExpand={(id) => setExpanded((e) => ({ ...e, [id]: !e[id] }))}
              />
            ))
          )}
        </div>

        <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, minHeight: 480, position: 'relative' }}>
          <DetailPane
            row={selected}
            lineageRow={selectedLineage}
            onServe={onServe}
            onMakeChampion={onMakeChampion}
            onDelete={onDelete}
            onAddCompare={addToCompare}
            busy={busy}
          />
        </div>
      </div>

      <CompareWorkspace
        slotA={slotA}
        slotB={slotB}
        onClear={clearCompare}
        prompt={cmpPrompt}
        onPrompt={setCmpPrompt}
        onRun={runCompare}
        busy={busy}
        result={cmpResult}
        lineageById={lineageById}
      />
    </div>
  );
}
