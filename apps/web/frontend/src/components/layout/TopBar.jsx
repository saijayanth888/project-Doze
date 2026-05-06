import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { C, F } from '../../config/colors';
import { apiFetch } from '../../config/api';
import LiveDot from '../shared/LiveDot';

const PAGE_LABELS = {
  '/dashboard':  'Dashboard',
  '/lineage':    'Lineage Tree',
  '/benchmarks': 'Benchmarks',
  '/playground': 'Playground',
  '/settings':   'Settings',
  '/adapters':   'Adapters',
  '/datasets':   'Datasets',
};

export default function TopBar({ champion = null }) {
  const location = useLocation();
  const [apiLive, setApiLive] = useState(null);
  const [gpuUtil, setGpuUtil] = useState(null);
  const [evolve, setEvolve] = useState(null);

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
    const iv = setInterval(fetchGpu, 5000);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    const poll = async () => {
      try {
        const s = await apiFetch('/api/evolve/status');
        setEvolve(s);
      } catch {
        setEvolve(null);
      }
    };
    poll();
    const iv = setInterval(poll, 5000);
    return () => clearInterval(iv);
  }, []);

  const page = PAGE_LABELS[location.pathname] || 'ModelForge';

  const gpuAvailable = gpuUtil?.gpu_available === true;
  const gpuUtilNum = typeof gpuUtil?.util_percent === 'number' ? gpuUtil.util_percent : null;
  const gpuUtilDisp = gpuUtilNum != null ? gpuUtilNum.toFixed(0) : '—';

  const vramUnified = gpuUtil?.vram_total_gb == null && gpuUtil?.vram_used_gb == null;
  const vramUsedDisp =
    gpuUtil?.vram_used_gb != null && Number.isFinite(Number(gpuUtil.vram_used_gb))
      ? Number(gpuUtil.vram_used_gb).toFixed(1)
      : '—';
  const vramTotalDisp =
    gpuUtil?.vram_total_gb != null && Number.isFinite(Number(gpuUtil.vram_total_gb))
      ? Number(gpuUtil.vram_total_gb).toFixed(0)
      : '—';

  const tempNum = typeof gpuUtil?.temp_celsius === 'number' ? gpuUtil.temp_celsius : null;
  const tempDisp = tempNum != null ? tempNum.toFixed(0) : '—';
  const tempTone = tempNum == null ? null : tempNum < 60 ? C.acc : tempNum < 80 ? C.warning : C.danger;

  return (
    <div
      className="mf-topbar"
      style={{
        height: 56,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 20px', flexShrink: 0, zIndex: 50,
      }}
    >
      {/* Back + breadcrumb */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, minWidth: 0 }}>
        <Link
          to="/"
          style={{
            fontFamily: F.ui,
            fontSize: 12,
            fontWeight: 500,
            color: C.txtM,
            textDecoration: 'none',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            flexShrink: 0,
            transition: 'color 150ms',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.color = C.txtP; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = C.txtM; }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M19 12H5M12 19l-7-7 7-7" />
          </svg>
          Back to home page
        </Link>
        <div style={{ width: 1, height: 16, background: C.border, flexShrink: 0 }} aria-hidden />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
          <Link
            to="/"
            style={{
              fontFamily: F.ui,
              fontSize: 13,
              color: C.txtM,
              textDecoration: 'none',
              transition: 'color 150ms',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.color = C.txtP; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = C.txtM; }}
          >
            ModelForge
          </Link>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={C.border} strokeWidth="2" aria-hidden><polyline points="9,18 15,12 9,6"/></svg>
          <span style={{ fontFamily: F.ui, fontSize: 13, color: C.txtP, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{page}</span>
        </div>
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
          <span
            title={[gpuUtil?.note, gpuUtil?.inference_note].filter(Boolean).join('\n\n') || undefined}
            style={{
              fontFamily: F.mono,
              fontSize: 11,
              color: tempTone || (gpuUtilNum != null && gpuUtilNum > 80 ? C.warning : C.txtS),
              maxWidth: 140,
              cursor: 'help',
            }}
          >
            {gpuAvailable
              ? `GPU ${gpuUtilDisp}% · ${tempNum != null ? `${tempDisp}°C` : '—°C'}`
              : 'GPU ·'}
          </span>
        </div>

        {/* VRAM / Unified Memory */}
        {gpuUtil?.gpu_available && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={C.txtM} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
              <path d="M2 20h20"/><rect x="4" y="4" width="16" height="12" rx="1"/>
              <path d="M8 4v12"/><path d="M16 4v12"/>
            </svg>
            <span
              title={
                vramUnified
                  ? gpuUtil?.unified_note
                    || 'NVIDIA GB10 / DGX Spark uses unified memory (CPU+GPU share system RAM).'
                  : undefined
              }
              style={{ fontFamily: F.mono, fontSize: 11, color: C.txtS, cursor: vramUnified ? 'help' : 'default' }}
            >
              {vramUnified
                ? gpuUtil?.unified_used_gb != null && gpuUtil?.unified_total_gb != null
                  ? `${Number(gpuUtil.unified_used_gb).toFixed(1)}/${Number(gpuUtil.unified_total_gb).toFixed(0)}GB shared`
                  : 'Unified Memory'
                : `${vramUsedDisp}/${vramTotalDisp}GB`}
            </span>
          </div>
        )}

        {/* Active runs */}
        <div
          style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          title={
            evolve?.status === 'running'
              ? `Evolution generation ${evolve.generation ?? '?'} · step ${evolve.current_step || '…'}`
              : 'No active evolution'
          }
        >
          {evolve?.status === 'running' ? (
            // Pulsing green dot when a run is active — gives the user a real
            // glance signal vs the neutral "idle" dot.
            <span style={{ position: 'relative', width: 10, height: 10, display: 'inline-block' }}>
              <span
                style={{
                  position: 'absolute',
                  inset: 0,
                  borderRadius: 999,
                  background: C.acc,
                  animation: 'mf-topbar-pulse 1.4s ease-out infinite',
                  opacity: 0.7,
                }}
              />
              <span
                style={{
                  position: 'absolute',
                  inset: 2,
                  borderRadius: 999,
                  background: C.acc,
                  boxShadow: `0 0 8px ${C.acc}`,
                }}
              />
            </span>
          ) : (
            <LiveDot idle />
          )}
          <span style={{ fontFamily: F.mono, fontSize: 11, color: evolve?.status === 'running' ? C.acc : C.txtM, fontWeight: evolve?.status === 'running' ? 600 : 400 }}>
            {evolve?.status === 'running'
              ? `Gen ${evolve.generation ?? '?'} running…`
              : 'idle'}
          </span>
        </div>

        {/* API status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <LiveDot color={apiLive ? C.success : C.danger} idle={apiLive === null} />
          <span style={{ fontFamily: F.mono, fontSize: 11, color: apiLive ? C.txtS : C.danger }}>
            {apiLive === null ? 'checking' : apiLive ? 'API' : 'offline'}
          </span>
        </div>

        {/* Generation / idle (avoid fake Gen 0 when no run) */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, borderLeft: `1px solid ${C.border}`, paddingLeft: 16 }}>
          {(champion?.generation ?? 0) > 0 ? (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={C.acc} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6" />
              <path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18" />
              <path d="M4 22h16" />
              <path d="M18 2H6v7a6 6 0 0 0 12 0V2Z" />
            </svg>
          ) : null}
          <span
            style={{
              fontFamily: F.mono,
              fontSize: 11,
              color:
                (champion?.generation ?? 0) > 0 || evolve?.status === 'running' || ((evolve?.generation ?? 0) > 0 && evolve?.run_id)
                  ? C.acc
                  : C.txtM,
              fontWeight: 600,
            }}
          >
            {(champion?.generation ?? 0) > 0
              ? `Gen ${champion.generation}`
              : evolve?.status === 'running' || ((evolve?.generation ?? 0) > 0 && evolve?.run_id)
                ? `Gen ${evolve.generation}`
                : 'Idle'}
          </span>
        </div>
      </div>
    </div>
  );
}
