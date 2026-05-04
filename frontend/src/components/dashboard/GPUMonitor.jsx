import { useEffect, useState } from 'react';
import { C, F } from '../../config/colors';
import { apiFetch } from '../../config/api';
import KPICard from '../shared/KPICard';

export default function GPUMonitor() {
  const [gpu, setGpu] = useState(null);

  useEffect(() => {
    const fetch = async () => {
      try { setGpu(await apiFetch('/api/system/gpu')); } catch {}
    };
    fetch();
    const iv = setInterval(fetch, 3000);
    return () => clearInterval(iv);
  }, []);

  if (!gpu) return null;

  if (!gpu.gpu_available) {
    return (
      <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: '14px 16px', display: 'flex', alignItems: 'center', gap: 12 }}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={C.txtM} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <rect x="4" y="8" width="16" height="12" rx="2"/><path d="M8 8V6"/><path d="M12 8V6"/><path d="M16 8V6"/>
        </svg>
        <div>
          <div style={{ fontFamily: F.ui, fontSize: 12, fontWeight: 600, color: C.txtS }}>Apple Silicon — CPU Inference</div>
          <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, marginTop: 2 }}>{gpu.note}</div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12 }}>
      <KPICard
        label="GPU Utilization"
        value={`${gpu.util_percent ?? '—'}%`}
        sub={gpu.gpu_name}
        valueColor={gpu.util_percent > 80 ? C.warning : C.acc}
        bar={gpu.util_percent != null ? { pct: gpu.util_percent, color: gpu.util_percent > 80 ? C.warning : C.acc } : null}
        live
      />
      <KPICard
        label="VRAM"
        value={`${gpu.vram_used_gb?.toFixed(1) ?? '—'}GB`}
        sub={`of ${gpu.vram_total_gb?.toFixed(0)}GB total`}
        bar={gpu.vram_total_gb ? { pct: (gpu.vram_used_gb / gpu.vram_total_gb) * 100, color: C.ind } : null}
      />
      <KPICard
        label="Temperature"
        value={`${gpu.temp_celsius ?? '—'}°C`}
        valueColor={gpu.temp_celsius > 85 ? C.danger : C.txtP}
        bar={gpu.temp_celsius != null ? { pct: (gpu.temp_celsius / 100) * 100, color: gpu.temp_celsius > 85 ? C.danger : C.info } : null}
      />
    </div>
  );
}
