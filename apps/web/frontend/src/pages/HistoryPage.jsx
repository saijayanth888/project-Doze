import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Archive,
  ArrowDownToLine,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Filter,
  History as HistoryIcon,
  Loader2,
  RefreshCw,
  Search,
  XCircle,
} from 'lucide-react';
import { C, F, BENCH_COLORS } from '../config/colors';
import { apiFetch } from '../config/api';
import { BENCHMARK_INFO } from '../data/benchmarkInfo';
import InfoTooltip from '../components/shared/InfoTooltip';
import LoadingSkeleton from '../components/shared/LoadingSkeleton';

// ── Helpers ───────────────────────────────────────────────────────────────

const STATUS_TONE = {
  running:   { fg: C.info,    Icon: Loader2,   label: 'running' },
  completed: { fg: C.acc,     Icon: CheckCircle2, label: 'completed' },
  stopped:   { fg: C.txtS,    Icon: XCircle,   label: 'stopped' },
  failed:    { fg: C.danger,  Icon: XCircle,   label: 'failed' },
  starting:  { fg: C.warning, Icon: Loader2,   label: 'starting' },
  idle:      { fg: C.txtS,    Icon: CheckCircle2, label: 'idle' },
};

function statusTone(s) {
  return STATUS_TONE[s] || { fg: C.txtS, Icon: HistoryIcon, label: s || 'unknown' };
}

function fmtDur(seconds) {
  if (!seconds && seconds !== 0) return '—';
  const s = Number(seconds);
  if (s < 60) return `${s.toFixed(0)}s`;
  if (s < 3600) return `${(s / 60).toFixed(1)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}

function fmtDate(ts) {
  if (!ts) return '—';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return String(ts);
  return d.toLocaleString();
}

function fmtAgo(ts) {
  if (!ts) return '—';
  const t = new Date(ts).getTime();
  if (!Number.isFinite(t)) return '—';
  const dt = (Date.now() - t) / 1000;
  if (dt < 60) return `${Math.floor(dt)}s ago`;
  if (dt < 3600) return `${Math.floor(dt / 60)}m ago`;
  if (dt < 86400) return `${Math.floor(dt / 3600)}h ago`;
  return `${Math.floor(dt / 86400)}d ago`;
}

function durationBetween(a, b) {
  if (!a) return null;
  const t1 = new Date(a).getTime();
  const t2 = b ? new Date(b).getTime() : Date.now();
  if (!Number.isFinite(t1) || !Number.isFinite(t2)) return null;
  return (t2 - t1) / 1000;
}

function input(extras = {}) {
  return {
    background: C.bgI, border: `1px solid ${C.border}`,
    borderRadius: 6, color: C.txtP, padding: '6px 10px',
    fontFamily: F.mono, fontSize: 12, outline: 'none', ...extras,
  };
}

function btn(kind = 'default', disabled = false) {
  const base = {
    display: 'inline-flex', alignItems: 'center', gap: 5,
    padding: '5px 10px', fontFamily: F.ui, fontSize: 11.5, fontWeight: 600,
    border: `1px solid ${C.border}`, borderRadius: 6,
    background: 'transparent', color: C.txtS,
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.55 : 1,
  };
  if (kind === 'primary') return { ...base, background: C.acc, color: '#0a0e16', border: 'none' };
  if (kind === 'danger') return { ...base, color: C.danger, borderColor: `${C.danger}55` };
  if (kind === 'ghost') return { ...base, padding: '3px 7px', fontSize: 11 };
  return base;
}

// ── Score sparkline ──────────────────────────────────────────────────────

function ScoreBar({ benchmark, score }) {
  const color = BENCH_COLORS[benchmark] || C.acc;
  const pct = Math.max(0, Math.min(1, Number(score || 0))) * 100;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: F.mono, fontSize: 10, color: C.txtS }}>
      <span style={{ minWidth: 70, textTransform: 'uppercase', letterSpacing: '0.04em', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        {benchmark}<InfoTooltip info={BENCHMARK_INFO[benchmark]} size={11} />
      </span>
      <div style={{ flex: 1, height: 6, background: C.bgI, borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color }} />
      </div>
      <span style={{ minWidth: 38, textAlign: 'right', color: C.txtP }}>{Number(score || 0).toFixed(3)}</span>
    </div>
  );
}

// ── Run row ──────────────────────────────────────────────────────────────

function RunRow({ run, expanded, onToggle, onArchive }) {
  const tone = statusTone(run.status);
  const SIcon = tone.Icon;
  const cfg = run.config || {};
  const dur = run.completed_at
    ? durationBetween(run.started_at, run.completed_at)
    : (run.status === 'running' ? durationBetween(run.started_at) : null);
  const finalScores = run.final_scores || {};
  const benchEntries = Object.entries(finalScores);

  return (
    <>
      <button type="button" onClick={onToggle} style={{
        width: '100%', textAlign: 'left', cursor: 'pointer',
        background: expanded ? C.bgE : 'transparent', border: 'none',
        borderTop: `1px solid ${C.border}`, padding: '10px 12px',
        display: 'grid', gridTemplateColumns: '14px 110px 1fr 130px 110px 100px 80px', gap: 10, alignItems: 'center',
      }}>
        {expanded ? <ChevronDown size={11} color={C.txtM} /> : <ChevronRight size={11} color={C.txtM} />}
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 5, fontFamily: F.mono,
          fontSize: 10.5, color: tone.fg, textTransform: 'uppercase', letterSpacing: '0.06em',
        }}>
          <SIcon size={11} className={run.status === 'running' || run.status === 'starting' ? 'spin' : ''} />
          {tone.label}
        </span>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontFamily: F.mono, fontSize: 12, color: C.txtP, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {run.run_id}
          </div>
          <div style={{ fontFamily: F.ui, fontSize: 11, color: C.txtM, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {cfg.base_model || run.base_model || '—'}
          </div>
        </div>
        <div style={{ fontFamily: F.mono, fontSize: 11, color: C.txtS }}>
          {fmtAgo(run.started_at)}
          <div style={{ fontSize: 9.5, color: C.txtM }}>{fmtDate(run.started_at)}</div>
        </div>
        <div style={{ fontFamily: F.mono, fontSize: 11, color: C.txtS }}>
          {fmtDur(dur)}
          <div style={{ fontSize: 9.5, color: C.txtM }}>
            {run.gens_persisted || 0}/{cfg.max_generations || run.generations_completed || '?'} gen
          </div>
        </div>
        <div style={{ fontFamily: F.mono, fontSize: 11.5, color: run.final_champion_score ? C.acc : C.txtM }}>
          {run.final_champion_score != null
            ? Number(run.final_champion_score).toFixed(3)
            : '—'}
          <div style={{ fontSize: 9.5, color: C.txtM, fontFamily: F.ui }}>
            {run.final_champion_score != null ? 'avg score' : 'no champion'}
          </div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 4 }}>
          {!run.archived_at && run.status !== 'running' ? (
            <button type="button" onClick={(e) => { e.stopPropagation(); onArchive(run); }}
                    title="Archive" style={btn('ghost')}>
              <Archive size={11} />
            </button>
          ) : null}
        </div>
      </button>
      {expanded ? (
        <div style={{ background: C.bgC, borderTop: `1px solid ${C.border}`, padding: '12px 16px 16px 32px' }}>
          {benchEntries.length > 0 ? (
            <>
              <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 6 }}>
                Champion scores
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 6, marginBottom: 12 }}>
                {benchEntries.map(([b, s]) => <ScoreBar key={b} benchmark={b} score={s} />)}
              </div>
            </>
          ) : null}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12, marginBottom: 6 }}>
            <Field label="Run ID" value={run.run_id} mono />
            <Field label="Status" value={run.status || '—'} />
            <Field label="Started" value={fmtDate(run.started_at)} mono />
            <Field label="Completed" value={fmtDate(run.completed_at)} mono />
            <Field label="Generations persisted" value={String(run.gens_persisted ?? 0)} />
            <Field label="Current step" value={run.current_step || '—'} mono />
            {run.error ? (
              <Field label="Error" value={run.error} mono color={C.danger} fullWidth />
            ) : null}
          </div>

          {Object.keys(cfg).length > 0 ? (
            <>
              <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, letterSpacing: '0.06em', textTransform: 'uppercase', marginTop: 6, marginBottom: 4 }}>
                Run config
              </div>
              <pre style={{ fontFamily: F.mono, fontSize: 10.5, color: C.txtS, background: C.bgI, border: `1px solid ${C.border}`, padding: 8, borderRadius: 4, overflowX: 'auto', maxHeight: 200 }}>
                {JSON.stringify(cfg, null, 2)}
              </pre>
            </>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

function Field({ label, value, mono = false, color = C.txtP, fullWidth = false }) {
  return (
    <div style={fullWidth ? { gridColumn: '1 / -1' } : undefined}>
      <div style={{ fontFamily: F.mono, fontSize: 9.5, color: C.txtM, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 2 }}>
        {label}
      </div>
      <div style={{ fontFamily: mono ? F.mono : F.ui, fontSize: mono ? 11 : 12, color, wordBreak: 'break-all' }}>
        {value || '—'}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────

const POLL_MS = 8000;

export default function HistoryPage() {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [statusFilter, setStatusFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState(null);
  const [err, setErr] = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await apiFetch(`/api/history/runs?include_archived=${includeArchived ? 'true' : 'false'}&limit=200`);
      setRuns(r?.runs || []);
      setErr(null);
    } catch (e) {
      setErr(e?.message || 'Failed to load runs');
      setRuns([]);
    } finally {
      setLoading(false);
    }
  }, [includeArchived]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { const iv = setInterval(load, POLL_MS); return () => clearInterval(iv); }, [load]);

  async function archiveRun(run) {
    if (!window.confirm(`Archive run ${run.run_id}?`)) return;
    try {
      await apiFetch(`/api/history/runs/${run.run_id}/archive`, { method: 'POST', body: '{}' });
      await load();
    } catch (e) {
      alert(`Archive failed: ${e?.message || 'unknown'}`);
    }
  }

  const filtered = useMemo(() => {
    let arr = runs;
    if (statusFilter !== 'all') arr = arr.filter((r) => r.status === statusFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      arr = arr.filter((r) => {
        const t = JSON.stringify({
          id: r.run_id, base: (r.config || {}).base_model || r.base_model,
          step: r.current_step, error: r.error,
        }).toLowerCase();
        return t.includes(q);
      });
    }
    return arr;
  }, [runs, statusFilter, search]);

  const counts = useMemo(() => {
    const c = { all: runs.length };
    for (const r of runs) c[r.status] = (c[r.status] || 0) + 1;
    return c;
  }, [runs]);

  const totalChampions = useMemo(
    () => runs.filter((r) => r.final_champion_score != null).length,
    [runs],
  );
  const avgChampion = useMemo(() => {
    const scs = runs.map((r) => r.final_champion_score).filter((s) => s != null);
    if (!scs.length) return null;
    return scs.reduce((a, b) => a + b, 0) / scs.length;
  }, [runs]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, padding: '8px 0 40px', maxWidth: 1700, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <HistoryIcon size={22} color={C.acc} />
        <div style={{ flex: 1 }}>
          <h1 style={{ fontFamily: F.display, fontSize: 26, color: C.txtP, margin: 0 }}>Run History</h1>
          <p style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM, margin: '4px 0 0' }}>
            Every evolution run that's ever started — promoted, discarded, archived — with the full config, final champion scores, and per-generation breakdown.
          </p>
        </div>
      </div>

      {/* Top stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
        <Stat label="Total runs" value={counts.all || 0} />
        <Stat label="Completed" value={counts.completed || 0} fg={C.acc} />
        <Stat label="Running" value={counts.running || 0} fg={C.info} />
        <Stat label="Failed" value={counts.failed || 0} fg={C.danger} />
        <Stat label="Champions promoted" value={totalChampions} />
        <Stat label="Avg champion" value={avgChampion != null ? avgChampion.toFixed(3) : '—'} fg={C.acc} />
      </div>

      {/* Filters */}
      <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 12, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, letterSpacing: '0.06em', textTransform: 'uppercase', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <Filter size={12} /> Filter
        </span>
        {['all', 'completed', 'running', 'stopped', 'failed'].map((s) => (
          <button key={s} type="button" onClick={() => setStatusFilter(s)} style={{
            padding: '4px 10px', fontFamily: F.ui, fontSize: 11,
            background: statusFilter === s ? C.accDim : 'transparent',
            border: `1px solid ${statusFilter === s ? C.borderA : C.border}`,
            color: statusFilter === s ? C.acc : C.txtS,
            borderRadius: 999, cursor: 'pointer', textTransform: 'capitalize',
          }}>
            {s} {counts[s] != null ? <span style={{ color: C.txtM }}>({counts[s]})</span> : null}
          </button>
        ))}
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginLeft: 'auto' }}>
          <Search size={12} color={C.txtM} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search run id, base model, step…"
            style={input({ width: 240 })}
          />
        </div>
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: F.ui, fontSize: 11.5, color: C.txtS, cursor: 'pointer' }}>
          <input type="checkbox" checked={includeArchived} onChange={(e) => setIncludeArchived(e.target.checked)} style={{ accentColor: C.acc }} />
          Show archived
        </label>
        <button type="button" onClick={load} style={btn('ghost')}>
          <RefreshCw size={11} /> Refresh
        </button>
      </div>

      {/* Runs table */}
      <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, overflow: 'hidden' }}>
        <div style={{
          display: 'grid', gridTemplateColumns: '14px 110px 1fr 130px 110px 100px 80px',
          gap: 10, padding: '10px 12px', fontFamily: F.mono, fontSize: 9.5,
          color: C.txtM, letterSpacing: '0.08em', textTransform: 'uppercase',
          background: C.bgI,
        }}>
          <span></span>
          <span>Status</span>
          <span>Run / Base model</span>
          <span>Started</span>
          <span>Duration</span>
          <span>Final avg</span>
          <span style={{ textAlign: 'right' }}>Actions</span>
        </div>
        {loading ? (
          <LoadingSkeleton rows={5} height={48} style={{ margin: 16 }} />
        ) : err ? (
          <div style={{ padding: 24, textAlign: 'center', color: C.danger, fontFamily: F.mono, fontSize: 12 }}>
            {err}
          </div>
        ) : filtered.length === 0 ? (
          <div style={{ padding: 32, textAlign: 'center', color: C.txtM, fontFamily: F.ui, fontSize: 13 }}>
            <Clock size={20} color={C.txtM} style={{ marginBottom: 6 }} />
            <div>No runs match the filter.</div>
            {runs.length === 0 ? <div style={{ marginTop: 4, fontSize: 11.5 }}>Start an evolution from the dashboard to populate this view.</div> : null}
          </div>
        ) : (
          filtered.map((r) => (
            <RunRow
              key={r.run_id}
              run={r}
              expanded={expanded === r.run_id}
              onToggle={() => setExpanded(expanded === r.run_id ? null : r.run_id)}
              onArchive={archiveRun}
            />
          ))
        )}
      </div>

      <style>{`
        .spin { animation: spin 1s linear infinite; }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}

function Stat({ label, value, fg = C.txtP }) {
  return (
    <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 12 }}>
      <div style={{ fontFamily: F.mono, fontSize: 9.5, color: C.txtM, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ fontFamily: F.display, fontSize: 24, color: fg, lineHeight: 1.1 }}>
        {value}
      </div>
    </div>
  );
}
