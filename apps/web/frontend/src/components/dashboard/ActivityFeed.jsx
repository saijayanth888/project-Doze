import { useEffect, useMemo, useState } from 'react';
import { C, F } from '../../config/colors';
import { apiFetch } from '../../config/api';

const STEP_LABELS = {
  init_run: 'Initialising run',
  initialising: 'Initialising run',
  identify_weaknesses: 'Identifying weaknesses',
  generate_training: 'Curating training data',
  train_adapter: 'Training LoRA adapter',
  evaluate: 'Evaluating across benchmarks',
  compare_to_champion: 'Comparing to champion',
  promote_or_discard: 'Promote / discard decision',
  next_or_finish: 'Advancing to next gen',
};

function fmtRelative(ts) {
  if (!ts) return '';
  const t = new Date(ts).getTime();
  if (!Number.isFinite(t)) return String(ts);
  const dt = Math.max(0, (Date.now() - t) / 1000);
  if (dt < 60) return `${Math.floor(dt)}s ago`;
  if (dt < 3600) return `${Math.floor(dt / 60)}m ago`;
  if (dt < 86400) return `${Math.floor(dt / 3600)}h ago`;
  return new Date(ts).toLocaleString();
}

export default function ActivityFeed() {
  const [events, setEvents] = useState([]);
  const [evolve, setEvolve] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    let cancelled = false;

    const load = async (silent = false) => {
      if (!silent) {
        setLoading(true);
        setError(null);
      }
      try {
        // Pull both DB-backed events AND the in-flight run status in parallel.
        const [acts, ev] = await Promise.all([
          apiFetch('/api/lineage/activity').catch((e) => { throw e; }),
          apiFetch('/api/evolve/status').catch(() => null),
        ]);
        if (!cancelled) {
          setEvents(Array.isArray(acts) ? acts : []);
          setEvolve(ev);
        }
      } catch (e) {
        if (!cancelled) {
          setEvents([]);
          setError(e?.status === 401 || e?.status === 403 ? 'API key missing or invalid — check Settings.' : 'Could not load activity feed.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load(false);
    // 2s polling while a run is active feels live without hammering the API.
    // The /lineage/activity + /evolve/status responses are tiny (<2KB each).
    const iv = setInterval(() => load(true), 2000);
    // Tick a "now" cursor so relative timestamps refresh between polls.
    const nowIv = setInterval(() => setNow(Date.now()), 1000);
    return () => { cancelled = true; clearInterval(iv); clearInterval(nowIv); };
  }, []);

  const isLive = evolve?.is_running === true || evolve?.status === 'running';

  // Synthesize a sticky "current run" row at the top whenever a run is in
  // flight. Always reflects the freshest step name + elapsed timer without
  // waiting for the orchestrator to write a DB event.
  const currentRow = useMemo(() => {
    if (!isLive) return null;
    const step = (evolve?.current_step || '').toLowerCase();
    const label = STEP_LABELS[step] || (step ? step.replace(/_/g, ' ') : 'working…');
    const elapsed = Math.max(0, Math.floor((evolve?.elapsed_seconds || 0)));
    const m = Math.floor(elapsed / 60);
    const s = elapsed % 60;
    return {
      id: `__live-${evolve?.run_id || 'run'}`,
      type: 'live_run',
      message: `${label} · gen ${evolve?.generation ?? '?'} · ${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')} elapsed`,
      timestamp: evolve?.started_at || new Date().toISOString(),
      run_id: evolve?.run_id,
    };
  }, [evolve, isLive, now]);

  const merged = currentRow ? [currentRow, ...events] : events;

  const labelFor = (ev) => ev.event || ev.message || ev.text || '';

  const metaFor = (ev) => {
    const type = ev.type || ev.event_type || '';
    const msg = String(ev.event || ev.message || ev.text || '');
    const lower = msg.toLowerCase();

    if (type === 'champion_promoted') return { icon: '🏆', color: C.acc };

    if (type === 'generation_complete') {
      // Backend may include promoted/discarded in the message; also respect an explicit `promoted` boolean if present.
      const promoted = typeof ev.promoted === 'boolean' ? ev.promoted : lower.includes('promoted') && !lower.includes('discarded');
      return { icon: promoted ? '✅' : '❌', color: promoted ? C.acc : C.danger };
    }

    if (type === 'training_started') return { icon: '🔧', color: C.ind };
    if (type === 'error') return { icon: '⚠️', color: C.warning };
    if (type === 'run_status') return { icon: '▶', color: C.ind };
    if (type === 'registry_snapshot') return { icon: '📁', color: C.txtM };
    if (type === 'live_run') return { icon: '◉', color: C.acc };

    return { icon: '•', color: C.txtS };
  };

  return (
    <div id="activity-feed" className="mf-card-hover" style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ padding: '14px 16px 12px', borderBottom: `1px solid ${C.border}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.txtM }}>Activity</span>
        <span
          title={isLive ? 'Polling /api/lineage/activity + /api/evolve/status every 2s while a run is in flight' : 'Polling every 2s'}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: F.mono, fontSize: 10, color: isLive ? C.acc : C.txtM, letterSpacing: '0.06em' }}
        >
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: 999,
              background: isLive ? C.acc : C.txtM,
              boxShadow: isLive ? `0 0 8px ${C.acc}` : 'none',
              animation: isLive ? 'mf-topbar-pulse 1.4s ease-out infinite' : 'none',
            }}
            aria-hidden
          />
          {isLive ? 'LIVE' : 'idle'}
        </span>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }}>
        {loading ? (
          <div style={{ padding: '20px 16px', fontFamily: F.ui, fontSize: 13, color: C.txtM }}>
            Loading activity…
          </div>
        ) : error ? (
          <div style={{ padding: '20px 16px', fontFamily: F.ui, fontSize: 13, color: C.danger, lineHeight: 1.5 }}>
            {error}
          </div>
        ) : merged.length === 0 ? (
          <div style={{ padding: '20px 16px', fontFamily: F.ui, fontSize: 13, color: C.txtM, lineHeight: 1.5 }}>
            No activity yet — this feed shows generation history from Postgres when available, otherwise the latest evolution
            run and champion snapshot from the API. If everything looks connected but this stays empty, the API may not reach
            Postgres — check Settings → Test Connections. For raw API server logs, use{' '}
            <span style={{ fontFamily: F.mono }}>docker compose logs api</span> (or your host equivalent).
          </div>
        ) : (
          merged.map((ev, i) => {
            const { icon, color } = metaFor(ev);
            const isLiveRow = ev.type === 'live_run';
            return (
              <div
                key={ev.id || i}
                style={{
                  display: 'flex',
                  gap: 10,
                  padding: '9px 16px',
                  alignItems: 'flex-start',
                  borderBottom: i < merged.length - 1 ? `1px solid rgba(30,41,59,0.5)` : 'none',
                  background: isLiveRow ? 'rgba(118,185,0,0.04)' : 'transparent',
                }}
              >
                <div
                  style={{
                    width: 20,
                    height: 20,
                    borderRadius: 8,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    background: `${color}22`,
                    border: `1px solid ${color}44`,
                    flexShrink: 0,
                    marginTop: 1,
                    position: 'relative',
                  }}
                >
                  {isLiveRow ? (
                    <span
                      style={{
                        position: 'absolute',
                        inset: -2,
                        borderRadius: 999,
                        background: color,
                        opacity: 0.45,
                        animation: 'mf-topbar-pulse 1.4s ease-out infinite',
                      }}
                      aria-hidden
                    />
                  ) : null}
                  <span aria-hidden style={{ fontSize: 12, lineHeight: 1, color, position: 'relative', zIndex: 1 }}>
                    {icon}
                  </span>
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: F.ui, fontSize: 12, color, lineHeight: 1.4, fontWeight: isLiveRow ? 600 : 400 }}>
                    {labelFor(ev)}
                  </div>
                  <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, marginTop: 3, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {isLiveRow ? <span style={{ color: C.acc }}>NOW</span> : <span>{fmtRelative(ev.timestamp || ev.time)}</span>}
                    {ev.run_id ? <span>· {ev.run_id}</span> : null}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
