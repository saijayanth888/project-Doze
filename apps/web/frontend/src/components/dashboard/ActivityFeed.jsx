import { useEffect, useState } from 'react';
import { C, F } from '../../config/colors';
import { apiFetch } from '../../config/api';

export default function ActivityFeed() {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    const load = async (silent = false) => {
      if (!silent) {
        setLoading(true);
        setError(null);
      }
      try {
        const data = await apiFetch('/api/lineage/activity');
        if (!cancelled) setEvents(Array.isArray(data) ? data : []);
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
    const iv = setInterval(() => load(true), 5000);
    return () => clearInterval(iv);
  }, []);

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

    return { icon: '•', color: C.txtS };
  };

  return (
    <div id="activity-feed" className="mf-card-hover" style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ padding: '14px 16px 12px', borderBottom: `1px solid ${C.border}` }}>
        <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.txtM }}>Activity</span>
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
        ) : events.length === 0 ? (
          <div style={{ padding: '20px 16px', fontFamily: F.ui, fontSize: 13, color: C.txtM, lineHeight: 1.5 }}>
            No activity yet — this feed shows generation history from Postgres when available, otherwise the latest evolution
            run and champion snapshot from the API. If everything looks connected but this stays empty, the API may not reach
            Postgres — check Settings → Test Connections. For raw API server logs, use{' '}
            <span style={{ fontFamily: F.mono }}>docker compose logs api</span> (or your host equivalent).
          </div>
        ) : (
          events.map((ev, i) => {
            const { icon, color } = metaFor(ev);
            return (
              <div
                key={ev.id || i}
                style={{
                  display: 'flex',
                  gap: 10,
                  padding: '9px 16px',
                  alignItems: 'flex-start',
                  borderBottom: i < events.length - 1 ? `1px solid rgba(30,41,59,0.5)` : 'none',
                }}
              >
                <div style={{ width: 20, height: 20, borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', background: `${color}22`, border: `1px solid ${color}44`, flexShrink: 0, marginTop: 1 }}>
                  <span aria-hidden style={{ fontSize: 12, lineHeight: 1, color }}>
                    {icon}
                  </span>
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: F.ui, fontSize: 12, color: color, lineHeight: 1.4 }}>{labelFor(ev)}</div>
                  <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, marginTop: 3 }}>{ev.timestamp || ev.time || '—'}</div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
