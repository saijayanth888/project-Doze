import { C, F } from '../../config/colors';

export default function MFLogo({ size = 28, collapsed = false }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <svg width={size * 0.75} height={size} viewBox="0 0 36 46" fill="none">
        <path d="M8 2 C8 12,20 12,20 23 C20 34,8 34,8 44" stroke={C.acc} strokeWidth="2.5" strokeLinecap="round" fill="none"/>
        <path d="M28 2 C28 12,16 12,16 23 C16 34,28 34,28 44" stroke={C.ind} strokeWidth="2.5" strokeLinecap="round" fill="none"/>
        <line x1="10" y1="12" x2="26" y2="12" stroke={C.acc} strokeWidth="1.5" strokeLinecap="round" opacity="0.7"/>
        <line x1="10" y1="23" x2="26" y2="23" stroke={C.ind} strokeWidth="1.5" strokeLinecap="round" opacity="0.7"/>
        <line x1="10" y1="34" x2="26" y2="34" stroke={C.acc} strokeWidth="1.5" strokeLinecap="round" opacity="0.7"/>
        <circle cx="8" cy="2" r="2.5" fill={C.acc}/>
        <circle cx="28" cy="2" r="2.5" fill={C.ind}/>
        <circle cx="8" cy="44" r="2.5" fill={C.acc}/>
        <circle cx="28" cy="44" r="2.5" fill={C.ind}/>
      </svg>
      {!collapsed && (
        <span style={{ fontFamily: F.ui, fontSize: size * 0.6, fontWeight: 700, letterSpacing: '-0.02em', lineHeight: 1 }}>
          <span style={{ color: C.txtP }}>Model</span>
          <span style={{ color: C.acc }}>Forge</span>
        </span>
      )}
    </div>
  );
}
