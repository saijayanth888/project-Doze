import { C, F } from '../../config/colors';
import LiveDot from './LiveDot';

const STYLES = {
  running:   { bg: 'rgba(34,197,94,0.12)',  color: C.success, border: 'rgba(34,197,94,0.3)' },
  promoted:  { bg: C.accDim,               color: C.acc,    border: C.borderA },
  discarded: { bg: 'rgba(239,68,68,0.12)', color: C.danger,  border: 'rgba(239,68,68,0.3)' },
  idle:      { bg: C.bgE,                  color: C.txtM,    border: C.border },
  warning:   { bg: 'rgba(245,158,11,0.12)',color: C.warning, border: 'rgba(245,158,11,0.3)' },
  training:  { bg: C.indDim,               color: C.ind,    border: C.borderI },
  info:      { bg: 'rgba(56,189,248,0.12)',color: C.info,    border: 'rgba(56,189,248,0.3)' },
};

export default function Badge({ type = 'idle', children }) {
  const s = STYLES[type] || STYLES.idle;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '2px 8px', borderRadius: 4,
      background: s.bg, color: s.color,
      border: `1px solid ${s.border}`,
      fontFamily: F.ui, fontSize: 10,
      fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
    }}>
      {type === 'running' && <LiveDot color={C.success} />}
      {children}
    </span>
  );
}
