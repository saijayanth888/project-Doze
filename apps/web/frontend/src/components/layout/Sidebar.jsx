import {
  LayoutDashboard,
  Layers,
  GitBranch,
  Database,
  BarChart2,
  MessageSquare,
  Settings2,
  Play,
  Bot,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { C, F } from '../../config/colors';
import MFLogo from '../shared/MFLogo';
import { useLocation, useNavigate } from 'react-router-dom';

const NAV = [
  { id: 'dashboard', path: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'adapters', path: '/adapters', label: 'Adapters', icon: Layers },
  { id: 'lineage', path: '/lineage', label: 'Lineage Tree', icon: GitBranch },
  { id: 'datasets', path: '/datasets', label: 'Datasets', icon: Database },
  { id: 'benchmarks', path: '/benchmarks', label: 'Benchmarks', icon: BarChart2 },
  { id: 'playground', path: '/playground', label: 'Playground', icon: MessageSquare },
  { id: 'automation', path: '/automation', label: 'Automation', icon: Bot },
  { id: 'settings', path: '/settings', label: 'Settings', icon: Settings2 },
];

export default function Sidebar({ collapsed, onToggle, champion }) {
  const location = useLocation();
  const navigate = useNavigate();

  return (
    <div
      className="mf-sidebar-rail"
      style={{
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
      }}
    >
      <div style={{ padding: '16px 14px 12px', borderBottom: `1px solid ${C.border}`, display: 'flex', alignItems: 'center', justifyContent: collapsed ? 'center' : 'space-between' }}>
        <MFLogo size={28} collapsed={collapsed} />
        {!collapsed && (
          <button type="button" onClick={onToggle} style={{ background: 'none', border: 'none', cursor: 'pointer', color: C.txtM, padding: 4, borderRadius: 4, display: 'flex', transition: 'color 150ms' }} aria-label="Collapse sidebar">
            <ChevronLeft size={14} />
          </button>
        )}
        {collapsed && (
          <button type="button" onClick={onToggle} style={{ background: 'none', border: 'none', cursor: 'pointer', color: C.txtM, padding: 0, display: 'flex' }} aria-label="Expand sidebar">
            <ChevronRight size={14} />
          </button>
        )}
      </div>

      {!collapsed && champion && (
        <button
          type="button"
          onClick={() => navigate('/playground')}
          title="Open Playground with champion model"
          style={{
            margin: '10px 12px',
            padding: '10px 12px',
            background: C.bgC,
            border: `1px solid rgba(118,185,0,0.2)`,
            borderRadius: 8,
            cursor: 'pointer',
            textAlign: 'left',
            width: 'calc(100% - 24px)',
            display: 'block',
          }}
        >
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: C.txtM, marginBottom: 4 }}>Champion</div>
          <div style={{ fontFamily: F.mono, fontSize: 12, color: C.acc, fontWeight: 600 }}>{champion.name || champion.base_model}</div>
          <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, marginTop: 2 }}>
            Gen {champion.generation} · {champion.avg_score?.toFixed(3) || '—'}
          </div>
          <div style={{ fontFamily: F.ui, fontSize: 10, color: C.acc, marginTop: 6, opacity: 0.9 }}>Click to open Playground →</div>
        </button>
      )}
      {collapsed && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '8px 0' }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: C.acc, boxShadow: `0 0 6px ${C.accGlow}` }} />
        </div>
      )}

      <div className="mf-sidebar-nav" style={{ flex: 1, padding: '8px 0', overflowY: 'auto' }}>
        {!collapsed && (
          <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: C.txtM, padding: '8px 16px 4px' }}>
            Navigation
          </div>
        )}
        {NAV.map((item) => {
          const Icon = item.icon;
          const isActive = location.pathname === item.path || (item.path === '/dashboard' && location.pathname === '/');
          return (
            <button
              key={item.id}
              type="button"
              data-active={isActive ? 'true' : 'false'}
              className="mf-sidebar-nav-btn"
              onClick={() => navigate(item.path)}
              title={collapsed ? item.label : undefined}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                width: '100%',
                padding: collapsed ? '10px 0' : '8px 16px',
                justifyContent: collapsed ? 'center' : 'flex-start',
                background: isActive ? 'rgba(118,185,0,0.06)' : 'transparent',
                border: 'none',
                borderLeft: collapsed ? 'none' : `2px solid ${isActive ? C.acc : 'transparent'}`,
                cursor: 'pointer',
                transition: 'background 150ms, border-color 150ms, color 150ms',
                outline: 'none',
              }}
            >
              <Icon size={16} strokeWidth={1.75} aria-hidden />
              {!collapsed && (
                <span className="mf-sidebar-nav-label" style={{ fontFamily: F.ui, fontSize: 13, fontWeight: isActive ? 600 : 400, whiteSpace: 'nowrap' }}>
                  {item.label}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div style={{ padding: collapsed ? '10px 0' : '12px', borderTop: `1px solid ${C.border}`, display: 'flex', justifyContent: collapsed ? 'center' : 'stretch' }}>
        {collapsed ? (
          <button
            type="button"
            className="mf-cta-primary"
            onClick={() => navigate('/dashboard?startEvolution=1')}
            aria-label="Start Evolution"
            style={{ width: 36, height: 36, background: C.acc, border: 'none', borderRadius: 6, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: `0 0 16px ${C.accGlow}`, color: '#000' }}
          >
            <Play size={14} fill="currentColor" />
          </button>
        ) : (
          <button
            type="button"
            className="mf-cta-primary"
            onClick={() => navigate('/dashboard?startEvolution=1')}
            style={{ width: '100%', padding: '10px', background: C.acc, color: '#000', border: 'none', borderRadius: 6, cursor: 'pointer', fontFamily: F.ui, fontSize: 13, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, boxShadow: `0 0 20px ${C.accGlow}` }}
          >
            <Play size={14} />
            Start Evolution
          </button>
        )}
      </div>
    </div>
  );
}
