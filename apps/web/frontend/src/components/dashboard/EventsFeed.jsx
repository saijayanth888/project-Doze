import { useEffect, useMemo, useRef, useState } from 'react';
import { CircleAlert, Database, FlaskConical, GitBranch, GraduationCap, Sparkles, Zap } from 'lucide-react';
import { C, F } from '../../config/colors';
import { apiFetch } from '../../config/api';

const POLL_MS = 2000;
const SOFT_CAP = 80; // most rows we render at once — keeps the DOM tiny.

const PHASE_META = {
  init:       { color: C.acc,     Icon: Sparkles,       label: 'init' },
  identify:   { color: '#a78bfa', Icon: GitBranch,      label: 'identify' },
  curate:     { color: '#fb923c', Icon: Database,       label: 'curate' },
  train:      { color: '#818cf8', Icon: GraduationCap,  label: 'train' },
  eval:       { color: '#2dd4bf', Icon: FlaskConical,   label: 'eval' },
  evaluate:   { color: '#2dd4bf', Icon: FlaskConical,   label: 'benchmark' },
  decide:     { color: '#facc15', Icon: Zap,            label: 'decide' },
  ensure:     { color: '#38bdf8', Icon: Sparkles,       label: 'download' },
  experiment: { color: '#38bdf8', Icon: FlaskConical,   label: 'experiment' },
  'campaign.started':  { color: C.acc,    Icon: Sparkles, label: 'campaign' },
  'campaign.complete': { color: C.acc,    Icon: Sparkles, label: 'campaign' },
  error:      { color: C.danger,  Icon: CircleAlert,    label: 'error' },
};

function metaFor(phase, level) {
  if (level === 'error') return { ...PHASE_META.error };
  if (level === 'warn') return { color: C.warning, Icon: CircleAlert, label: phase };
  return PHASE_META[phase] || { color: C.txtS, Icon: Sparkles, label: phase || '·' };
}

function fmtSecsAgo(tsSeconds, now) {
  const dt = Math.max(0, now / 1000 - tsSeconds);
  if (dt < 60) return `${Math.floor(dt)}s ago`;
  if (dt < 3600) return `${Math.floor(dt / 60)}m ago`;
  if (dt < 86400) return `${Math.floor(dt / 3600)}h ago`;
  return new Date(tsSeconds * 1000).toLocaleString();
}

export default function EventsFeed() {
  const [runId, setRunId] = useState(null);
  const [events, setEvents] = useState([]);
  // Filter pills — empty set = show everything.
  const [activePhases, setActivePhases] = useState(() => new Set());
  const [autoScroll, setAutoScroll] = useState(true);
  const [now, setNow] = useState(Date.now());
  const sinceRef = useRef(-1);
  const listRef = useRef(null);

  // Watch /api/evolve/status AND /api/campaigns/status. Pick whichever has
  // an active run; idle ones are ignored. Switching runs clears the buffer.
  // Idle on both → drop the run id entirely so we stop polling /events.
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const [evo, camp] = await Promise.all([
          apiFetch('/api/evolve/status').catch(() => null),
          apiFetch('/api/campaigns/status').catch(() => null),
        ]);
        if (cancelled) return;
        const evoRunning = evo?.is_running === true || evo?.status === 'running';
        const campActive =
          camp?.status && camp.status !== 'idle' && camp.status !== 'completed' && camp.status !== 'failed';
        // Prefer campaign run id when a campaign is active (eval-only flow);
        // fall back to evolve run id when an evolution is running. Idle on
        // both → null, which stops the events poll below.
        let rid = null;
        if (campActive && camp?.run_id) rid = camp.run_id;
        else if (evoRunning && evo?.run_id) rid = evo.run_id;
        if (rid !== runId) {
          setRunId(rid);
          setEvents([]);
          sinceRef.current = -1;
        }
      } catch {
        /* polled again next tick */
      }
    };
    tick();
    const iv = setInterval(tick, POLL_MS);
    return () => { cancelled = true; clearInterval(iv); };
  }, [runId]);

  // Once we know the run id, poll the events endpoint incrementally with
  // ?since=<last_id> so each tick only ships newly-arrived events.
  useEffect(() => {
    if (!runId) return undefined;
    let cancelled = false;
    const tick = async () => {
      try {
        const data = await apiFetch(`/api/evolve/${runId}/events?since=${sinceRef.current}`);
        if (cancelled) return;
        const incoming = Array.isArray(data?.events) ? data.events : [];
        if (!incoming.length) return;
        sinceRef.current = data.next_since ?? sinceRef.current;
        setEvents((prev) => {
          const combined = [...prev, ...incoming];
          // Cap so the DOM and re-render cost stay bounded on very long runs.
          return combined.length > SOFT_CAP * 4
            ? combined.slice(-SOFT_CAP * 4)
            : combined;
        });
      } catch {
        /* try again next tick */
      }
    };
    tick();
    const iv = setInterval(tick, POLL_MS);
    return () => { cancelled = true; clearInterval(iv); };
  }, [runId]);

  // Cheap "now" cursor so the relative timestamps refresh between polls.
  useEffect(() => {
    const iv = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(iv);
  }, []);

  // Scroll to bottom when new events arrive — but only if the user hasn't
  // scrolled up to read history.
  useEffect(() => {
    if (!autoScroll || !listRef.current) return;
    listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [events.length, autoScroll]);

  const phaseCounts = useMemo(() => {
    const m = new Map();
    for (const e of events) m.set(e.phase, (m.get(e.phase) || 0) + 1);
    return m;
  }, [events]);

  const togglePhase = (p) =>
    setActivePhases((curr) => {
      const next = new Set(curr);
      if (next.has(p)) next.delete(p);
      else next.add(p);
      return next;
    });

  const filtered = activePhases.size === 0
    ? events
    : events.filter((e) => activePhases.has(e.phase));

  const visible = filtered.slice(-SOFT_CAP);

  return (
    <div
      className="mf-card-hover"
      style={{
        background: C.bgC,
        border: `1px solid ${C.border}`,
        borderRadius: 8,
        padding: 0,
        display: 'flex',
        flexDirection: 'column',
        height: 320,
      }}
    >
      <div
        style={{
          padding: '12px 16px',
          borderBottom: `1px solid ${C.border}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: 999,
              background: runId ? C.acc : C.txtM,
              boxShadow: runId ? `0 0 8px ${C.acc}` : 'none',
              animation: runId ? 'mf-topbar-pulse 1.4s ease-out infinite' : 'none',
            }}
            aria-hidden
          />
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
            Live Events
          </span>
          {runId ? (
            <span style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM }}>
              · {runId} · {events.length} events
            </span>
          ) : (
            <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM }}>
              · waiting for an active run
            </span>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          {Object.entries(PHASE_META).map(([p, m]) => {
            const count = phaseCounts.get(p) || 0;
            if (!count && p !== 'eval' && p !== 'train') return null;
            const active = activePhases.has(p);
            const muted = activePhases.size > 0 && !active;
            return (
              <button
                key={p}
                type="button"
                onClick={() => togglePhase(p)}
                style={{
                  padding: '2px 8px',
                  fontSize: 10,
                  fontFamily: F.mono,
                  textTransform: 'uppercase',
                  letterSpacing: '0.06em',
                  color: muted ? C.txtM : m.color,
                  background: active ? `${m.color}22` : muted ? 'transparent' : `${m.color}10`,
                  border: `1px solid ${active ? m.color : C.border}`,
                  borderRadius: 999,
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                }}
                title={
                  active
                    ? `Hide ${p} events (${count})`
                    : activePhases.size === 0
                      ? `Filter to ${p} only (${count})`
                      : `Show ${p} too (${count})`
                }
              >
                {p}
                {count ? <span style={{ color: C.txtM }}>{count}</span> : null}
              </button>
            );
          })}
          <button
            type="button"
            onClick={() => setAutoScroll((v) => !v)}
            style={{
              padding: '2px 8px',
              fontSize: 10,
              fontFamily: F.mono,
              color: autoScroll ? C.acc : C.txtM,
              background: autoScroll ? `${C.acc}10` : 'transparent',
              border: `1px solid ${autoScroll ? C.acc : C.border}`,
              borderRadius: 999,
              cursor: 'pointer',
            }}
            title="Auto-scroll on new events"
          >
            {autoScroll ? 'follow' : 'paused'}
          </button>
        </div>
      </div>

      <div
        ref={listRef}
        onScroll={(e) => {
          // If the user scrolls away from the bottom, stop auto-following.
          // When they scroll back to the bottom, resume.
          const el = e.currentTarget;
          const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
          if (atBottom !== autoScroll) setAutoScroll(atBottom);
        }}
        style={{
          flex: 1,
          overflowY: 'auto',
          fontFamily: F.mono,
          fontSize: 11.5,
          lineHeight: 1.5,
          padding: '6px 0',
        }}
      >
        {!runId ? (
          <div style={{ padding: '24px 16px', color: C.txtM, fontFamily: F.ui }}>
            Once an evolution run starts, every meaningful step lands here in real time —
            curation per-source, train/eval phase boundaries, per-benchmark scores, and
            the promote/discard decision.
          </div>
        ) : events.length === 0 ? (
          <div style={{ padding: '24px 16px', color: C.txtM, fontFamily: F.ui }}>
            Connected to <span style={{ fontFamily: F.mono, color: C.txtS }}>{runId}</span> — waiting for the first event…
          </div>
        ) : (
          visible.map((ev) => {
            const meta = metaFor(ev.phase, ev.level);
            const Icon = meta.Icon;
            return (
              <div
                key={ev.id}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '64px 18px 1fr auto',
                  gap: 10,
                  padding: '4px 14px',
                  alignItems: 'flex-start',
                }}
              >
                <span style={{ color: C.txtM, fontSize: 10, marginTop: 3 }}>{fmtSecsAgo(ev.ts, now)}</span>
                <span
                  title={`${meta.label}${ev.generation != null ? ` · gen ${ev.generation}` : ''}`}
                  style={{
                    width: 18,
                    height: 18,
                    borderRadius: 4,
                    background: `${meta.color}22`,
                    border: `1px solid ${meta.color}55`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                    marginTop: 2,
                  }}
                >
                  <Icon size={11} color={meta.color} />
                </span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ color: meta.color, wordBreak: 'break-word' }}>
                    {ev.label}
                  </div>
                  {ev.sub ? (
                    <div style={{ color: C.txtM, fontSize: 10.5, marginTop: 1 }}>{ev.sub}</div>
                  ) : null}
                </div>
                {ev.generation != null ? (
                  <span
                    style={{
                      fontSize: 9,
                      color: C.txtM,
                      background: 'rgba(255,255,255,0.04)',
                      padding: '1px 6px',
                      borderRadius: 999,
                      whiteSpace: 'nowrap',
                      marginTop: 3,
                    }}
                  >
                    gen {ev.generation}
                  </span>
                ) : null}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
