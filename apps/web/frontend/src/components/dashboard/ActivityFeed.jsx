import { useEffect, useState } from 'react';
import { C, F } from '../../config/colors';
import { apiFetch } from '../../config/api';
import { GENS } from '../../config/mockData';

const EVENT_COLORS = {
  promote:  C.acc,
  discard:  C.danger,
  training: C.ind,
  eval:     C.info,
  started:  C.success,
  weakness: C.warning,
};

function buildMockFeed(gens) {
  return gens.slice(-8).reverse().map(g => ({
    type: g.promoted ? 'promote' : 'discard',
    text: `Gen ${g.generation} ${g.promoted ? `promoted via ${g.method}` : `discarded — ${g.decision_reason}`}`,
    time: `${Math.floor(Math.random() * 60)}m ago`,
    avg_score: g.avg_score,
  }));
}

export default function ActivityFeed() {
  const [events, setEvents] = useState(buildMockFeed(GENS));

  useEffect(() => {
    apiFetch('/api/lineage/activity')
      .then(data => { if (data?.length) setEvents(data); })
      .catch(() => {});
    const iv = setInterval(() => {
      apiFetch('/api/lineage/activity').then(data => { if (data?.length) setEvents(data); }).catch(() => {});
    }, 5000);
    return () => clearInterval(iv);
  }, []);

  return (
    <div id="activity-feed" className="mf-card-hover" style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ padding: '14px 16px 12px', borderBottom: `1px solid ${C.border}` }}>
        <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.txtM }}>Activity</span>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }}>
        {events.map((ev, i) => {
          const color = EVENT_COLORS[ev.type] || C.txtS;
          return (
            <div key={i} style={{ display: 'flex', gap: 10, padding: '9px 16px', alignItems: 'flex-start', borderBottom: i < events.length - 1 ? `1px solid rgba(30,41,59,0.5)` : 'none' }}>
              <div style={{ width: 7, height: 7, borderRadius: '50%', background: color, flexShrink: 0, marginTop: 5, boxShadow: `0 0 5px ${color}66` }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontFamily: F.ui, fontSize: 12, color: C.txtS, lineHeight: 1.4 }}>{ev.event || ev.text}</div>
                <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, marginTop: 3 }}>{ev.time || '—'}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
