import { C, F } from '../../config/colors';
import MFLogo from '../shared/MFLogo';
import { useLocation, useNavigate } from 'react-router-dom';

const NAV = [
  { id: 'dashboard',  path: '/dashboard',  label: 'Dashboard',   icon: 'grid' },
  { id: 'lineage',    path: '/lineage',     label: 'Lineage Tree',icon: 'branch' },
  { id: 'benchmarks', path: '/benchmarks',  label: 'Benchmarks',  icon: 'bar' },
  { id: 'playground', path: '/playground',  label: 'Playground',  icon: 'chat' },
  { id: 'settings',   path: '/settings',    label: 'Settings',    icon: 'settings' },
];

function NavIcon({ name }) {
  const p = { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.75, strokeLinecap: 'round', strokeLinejoin: 'round' };
  if (name === 'grid')     return <svg {...p}><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>;
  if (name === 'branch')   return <svg {...p}><line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/></svg>;
  if (name === 'bar')      return <svg {...p}><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>;
  if (name === 'chat')     return <svg {...p}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>;
  if (name === 'settings') return <svg {...p}><circle cx="12" cy="12" r="3"/><path d="M19.07 4.93A10 10 0 1 0 4.93 19.07"/></svg>;
  return null;
}

export default function Sidebar({ collapsed, onToggle, champion }) {
  const location = useLocation();
  const navigate = useNavigate();

  return (
    <div style={{
      width: collapsed ? 64 : 240,
      minWidth: collapsed ? 64 : 240,
      background: C.bgS,
      borderRight: `1px solid ${C.border}`,
      display: 'flex',
      flexDirection: 'column',
      transition: 'width 250ms cubic-bezier(0.16,1,0.3,1)',
      overflow: 'hidden',
      position: 'relative',
      zIndex: 20,
      height: '100vh',
    }}>
      {/* Logo row */}
      <div style={{ padding: '16px 14px 12px', borderBottom: `1px solid ${C.border}`, display: 'flex', alignItems: 'center', justifyContent: collapsed ? 'center' : 'space-between' }}>
        <MFLogo size={28} collapsed={collapsed} />
        {!collapsed && (
          <button onClick={onToggle} style={{ background: 'none', border: 'none', cursor: 'pointer', color: C.txtM, padding: 4, borderRadius: 4, display: 'flex', transition: 'color 150ms' }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="15,18 9,12 15,6"/></svg>
          </button>
        )}
        {collapsed && (
          <button onClick={onToggle} style={{ background: 'none', border: 'none', cursor: 'pointer', color: C.txtM, padding: 0, display: 'flex' }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="9,18 15,12 9,6"/></svg>
          </button>
        )}
      </div>

      {/* Champion box */}
      {!collapsed && champion && (
        <div style={{ margin: '10px 12px', padding: '10px 12px', background: C.bgC, border: `1px solid rgba(118,185,0,0.2)`, borderRadius: 8 }}>
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: C.txtM, marginBottom: 4 }}>Champion</div>
          <div style={{ fontFamily: F.mono, fontSize: 12, color: C.acc, fontWeight: 600 }}>{champion.name || champion.base_model}</div>
          <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, marginTop: 2 }}>
            Gen {champion.generation} · {champion.avg_score?.toFixed(3) || '—'}
          </div>
        </div>
      )}
      {collapsed && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '8px 0' }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: C.acc, boxShadow: `0 0 6px ${C.accGlow}` }} />
        </div>
      )}

      {/* Nav */}
      <div style={{ flex: 1, padding: '8px 0', overflowY: 'auto' }}>
        {!collapsed && (
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: C.txtM, padding: '8px 16px 4px' }}>
            Navigation
          </div>
        )}
        {NAV.map(item => {
          const isActive = location.pathname === item.path || (item.path === '/dashboard' && location.pathname === '/');
          return (
            <button
              key={item.id}
              onClick={() => navigate(item.path)}
              title={collapsed ? item.label : undefined}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                width: '100%', padding: collapsed ? '10px 0' : '8px 16px',
                justifyContent: collapsed ? 'center' : 'flex-start',
                background: isActive ? 'rgba(118,185,0,0.06)' : 'transparent',
                border: 'none',
                borderLeft: collapsed ? 'none' : `2px solid ${isActive ? C.acc : 'transparent'}`,
                cursor: 'pointer', transition: 'all 150ms', outline: 'none',
                color: isActive ? C.acc : C.txtM,
              }}
            >
              <NavIcon name={item.icon} />
              {!collapsed && (
                <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: isActive ? 600 : 400, color: isActive ? C.acc : C.txtM, whiteSpace: 'nowrap' }}>
                  {item.label}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Start Evolution CTA */}
      <div style={{ padding: collapsed ? '10px 0' : '12px', borderTop: `1px solid ${C.border}`, display: 'flex', justifyContent: collapsed ? 'center' : 'stretch' }}>
        {collapsed ? (
          <button onClick={() => navigate('/dashboard')} style={{ width: 36, height: 36, background: C.acc, border: 'none', borderRadius: 6, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: `0 0 16px ${C.accGlow}` }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#000" strokeWidth="2.5" strokeLinecap="round"><polygon points="5,3 19,12 5,21"/></svg>
          </button>
        ) : (
          <button onClick={() => navigate('/dashboard')} style={{ width: '100%', padding: '10px', background: C.acc, color: '#000', border: 'none', borderRadius: 6, cursor: 'pointer', fontFamily: F.ui, fontSize: 13, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, boxShadow: `0 0 20px ${C.accGlow}`, transition: 'all 150ms' }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polygon points="5,3 19,12 5,21"/></svg>
            Start Evolution
          </button>
        )}
      </div>
    </div>
  );
}
