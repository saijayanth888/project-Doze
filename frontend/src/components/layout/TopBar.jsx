import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { C, F } from '../../config/colors';
import { apiFetch } from '../../config/api';
import LiveDot from '../shared/LiveDot';

const PAGE_LABELS = {
  '/dashboard':  'Dashboard',
  '/lineage':    'Lineage Tree',
  '/benchmarks': 'Benchmarks',
  '/playground': 'Playground',
  '/settings':   'Settings',
};

export default function TopBar() {
  const location = useLocation();
  const [apiLive, setApiLive] = useState(null);
  const [gpuUtil, setGpuUtil] = useState(null);

  useEffect(() => {
    const check = async () => {
      try {
        await apiFetch('/api/system/status');
        setApiLive(true);
      } catch {
        setApiLive(false);
      }
    };
    check();
    const iv = setInterval(check, 5000);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    const fetchGpu = async () => {
      try {
        const data = await apiFetch('/api/system/gpu');
        setGpuUtil(data);
      } catch {}
    };
    fetchGpu();
    const iv = setInterval(fetchGpu, 3000);
    return () => clearInterval(iv);
  }, []);

  const page = PAGE_LABELS[location.pathname] || 'ModelForge';

  return (
    <div style={{
      height: 56, background: C.bgS, borderBottom: `1px solid ${C.border}`,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '0 20px', flexShrink: 0, zIndex: 50,
    }}>
      {/* Breadcrumb */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM }}>ModelForge</span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={C.border} strokeWidth="2"><polyline points="9,18 15,12 9,6"/></svg>
        <span style={{ fontFamily: F.ui, fontSize: 13, color: C.txtP, fontWeight: 500 }}>{page}</span>
      </div>

      {/* Right metrics */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
        {/* GPU */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={C.txtM} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
            <rect x="4" y="8" width="16" height="12" rx="2"/>
            <path d="M8 8V6"/><path d="M12 8V6"/><path d="M16 8V6"/>
            <path d="M8 20v2"/><path d="M12 20v2"/><path d="M16 20v2"/>
          </svg>
          <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtS }}>
            {gpuUtil?.gpu_available ? `GPU ${gpuUtil.util_percent ?? '—'}%` : 'CPU'}
          </span>
        </div>

        {/* VRAM */}
        {gpuUtil?.gpu_available && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={C.txtM} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
              <path d="M2 20h20"/><rect x="4" y="4" width="16" height="12" rx="1"/>
              <path d="M8 4v12"/><path d="M16 4v12"/>
            </svg>
            <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtS }}>
              {gpuUtil.vram_used_gb?.toFixed(1)}/{gpuUtil.vram_total_gb?.toFixed(0)}GB
            </span>
          </div>
        )}

        {/* API status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <LiveDot color={apiLive ? C.acc : C.danger} idle={apiLive === null} />
          <span style={{ fontFamily: F.mono, fontSize: 11, color: apiLive ? C.acc : C.danger }}>
            {apiLive === null ? 'checking' : apiLive ? 'API LIVE' : 'MOCK DATA'}
          </span>
        </div>

        {/* Champion trophy */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, borderLeft: `1px solid ${C.border}`, paddingLeft: 16 }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={C.acc} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
            <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/>
            <path d="M4 22h16"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/>
          </svg>
          <span style={{ fontFamily: F.mono, fontSize: 11, color: C.acc, fontWeight: 600 }}>
            Gen 25
          </span>
        </div>
      </div>
    </div>
  );
}
