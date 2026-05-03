import { C, F } from '../../config/colors';
import LiveDot from './LiveDot';

export default function KPICard({ label, value, sub, valueColor, bar = null, live = false }) {
  return (
    <div style={{
      background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8,
      padding: '14px 16px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 6 }}>
        {live && <LiveDot />}
        <span style={{ fontFamily: F.ui, fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: C.txtM }}>
          {label}
        </span>
      </div>
      <div style={{ fontFamily: F.mono, fontSize: '1.75rem', fontWeight: 500, lineHeight: 1, color: valueColor || C.txtP }}>
        {value}
      </div>
      {sub && <div style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM, marginTop: 4 }}>{sub}</div>}
      {bar !== null && (
        <div style={{ marginTop: 8, height: 3, background: C.bgE, borderRadius: 2, overflow: 'hidden' }}>
          <div style={{ width: `${bar.pct}%`, height: '100%', background: bar.color || C.acc, borderRadius: 2 }} />
        </div>
      )}
    </div>
  );
}
