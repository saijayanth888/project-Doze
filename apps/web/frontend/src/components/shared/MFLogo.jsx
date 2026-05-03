import { C, F } from '../../config/colors';

export default function MFLogo({ size = 28, collapsed = false }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <svg width={size * 0.8} height={size} viewBox="0 0 36 40" fill="none">
        <path d="M8 2 C8 10, 20 10, 20 20 C20 30, 8 30, 8 38" stroke={C.acc} strokeWidth="2.5" strokeLinecap="round" fill="none"/>
        <path d="M28 2 C28 10, 16 10, 16 20 C16 30, 28 30, 28 38" stroke={C.ind} strokeWidth="2.5" strokeLinecap="round" fill="none"/>
        <line x1="10" y1="10" x2="26" y2="10" stroke={C.acc} strokeWidth="1.5" strokeLinecap="round" opacity="0.7"/>
        <line x1="10" y1="20" x2="26" y2="20" stroke={C.ind} strokeWidth="1.5" strokeLinecap="round" opacity="0.7"/>
        <line x1="10" y1="30" x2="26" y2="30" stroke={C.acc} strokeWidth="1.5" strokeLinecap="round" opacity="0.7"/>
        <circle cx="8" cy="2" r="2.5" fill={C.acc}/>
        <circle cx="28" cy="2" r="2.5" fill={C.ind}/>
        <circle cx="8" cy="38" r="2.5" fill={C.acc}/>
        <circle cx="28" cy="38" r="2.5" fill={C.ind}/>
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
