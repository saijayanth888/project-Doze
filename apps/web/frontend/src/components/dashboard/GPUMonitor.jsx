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
    const iv = setInterval(fetch, 5000);
    return () => clearInterval(iv);
  }, []);

  if (!gpu) {
    return (
      <div className="mf-card-hover" style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 18, height: '100%', boxSizing: 'border-box' }}>
        <span style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM }}>Loading GPU telemetry…</span>
      </div>
    );
  }

  const utilNum = typeof gpu.util_percent === 'number' ? gpu.util_percent : null;
  const utilDisp = utilNum != null ? utilNum.toFixed(0) : '—';

  const vramUsedN = gpu.vram_used_gb != null ? Number(gpu.vram_used_gb) : null;
  const vramTotalN = gpu.vram_total_gb != null ? Number(gpu.vram_total_gb) : null;
  const unifiedMemory = vramTotalN == null && vramUsedN == null;

  // DGX Spark unified memory: API enriches the payload with system-RAM totals
  // so we can show a real value instead of just "Unified Memory".
  const unifiedTotalN = gpu.unified_total_gb != null ? Number(gpu.unified_total_gb) : null;
  const unifiedUsedN = gpu.unified_used_gb != null ? Number(gpu.unified_used_gb) : null;
  const unifiedTotal = unifiedTotalN != null && Number.isFinite(unifiedTotalN) ? unifiedTotalN.toFixed(0) : null;
  const unifiedUsed = unifiedUsedN != null && Number.isFinite(unifiedUsedN) ? unifiedUsedN.toFixed(1) : null;
  const unifiedBarPct =
    unifiedTotalN != null && unifiedTotalN > 0 && unifiedUsedN != null && Number.isFinite(unifiedUsedN)
      ? (unifiedUsedN / unifiedTotalN) * 100
      : null;

  const vramUsed = vramUsedN != null && Number.isFinite(vramUsedN) ? vramUsedN.toFixed(1) : '—';
  const vramTotal = vramTotalN != null && Number.isFinite(vramTotalN) ? vramTotalN.toFixed(0) : '—';

  const tempNum = typeof gpu.temp_celsius === 'number' ? gpu.temp_celsius : null;
  const tempDisp = tempNum != null ? tempNum.toFixed(0) : '—';

  const tempTone =
    tempNum == null ? null : tempNum < 60 ? C.acc : tempNum < 80 ? C.warning : C.danger;
  const vramBarPct =
    vramTotalN != null && vramTotalN > 0 && vramUsedN != null && Number.isFinite(vramUsedN)
      ? (vramUsedN / vramTotalN) * 100
      : null;

  if (!gpu.gpu_available) {
    if (gpu.ollama_inference_ok) {
      return (
        <div
          className="mf-card-hover"
          style={{
            background: C.bgC,
            border: `1px solid rgba(118,185,0,0.35)`,
            borderRadius: 8,
            padding: '14px 16px',
            display: 'flex',
            alignItems: 'flex-start',
            gap: 12,
          }}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={C.acc} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, marginTop: 2 }}>
            <rect x="4" y="8" width="16" height="12" rx="2"/><path d="M8 8V6"/><path d="M12 8V6"/><path d="M16 8V6"/>
          </svg>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontFamily: F.ui, fontSize: 12, fontWeight: 600, color: C.acc }}>
              Ollama · GPU inference (DGX Spark)
            </div>
            <div style={{ fontFamily: F.ui, fontSize: 11, color: C.txtS, marginTop: 6, lineHeight: 1.5 }}>
              The Ollama service is up with the <span style={{ fontFamily: F.mono }}>gpu</span> Compose profile — models run on NVIDIA here. Charts above appear when this API container can run <span style={{ fontFamily: F.mono }}>nvidia-smi</span> (GPU passed into <span style={{ fontFamily: F.mono }}>api</span>).
            </div>
          </div>
        </div>
      );
    }
    return (
      <div className="mf-card-hover" style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: '14px 16px', display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={C.txtM} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, marginTop: 2 }}>
          <rect x="4" y="8" width="16" height="12" rx="2"/><path d="M8 8V6"/><path d="M12 8V6"/><path d="M16 8V6"/>
        </svg>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontFamily: F.ui, fontSize: 12, fontWeight: 600, color: C.txtS }}>
            No GPU telemetry yet
          </div>
          <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, marginTop: 6, lineHeight: 1.45 }}>
            {gpu.note}
          </div>
          {gpu.inference_note ? (
            <div style={{ fontFamily: F.ui, fontSize: 10, color: C.txtS, marginTop: 8, lineHeight: 1.5 }}>
              {gpu.inference_note}
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12 }}>
      <KPICard
        label="GPU Utilization"
        value={`${utilDisp}%`}
        sub={gpu.gpu_name || gpu.device || 'GPU'}
        valueColor={utilNum != null && utilNum > 80 ? C.warning : C.acc}
        bar={utilNum != null ? { pct: utilNum, color: utilNum > 80 ? C.warning : C.acc } : null}
        live
      />
      <KPICard
        label={unifiedMemory ? 'Unified Memory' : 'VRAM'}
        value={
          unifiedMemory
            ? unifiedUsed != null
              ? `${unifiedUsed}GB`
              : 'Unified'
            : `${vramUsed}GB`
        }
        sub={
          unifiedMemory
            ? unifiedTotal != null
              ? `of ${unifiedTotal}GB system RAM (CPU+GPU share one pool)`
              : 'CPU + GPU share one pool of memory'
            : `of ${vramTotal}GB total`
        }
        bar={
          unifiedMemory
            ? unifiedBarPct != null
              ? { pct: unifiedBarPct, color: C.ind }
              : null
            : vramBarPct != null
              ? { pct: vramBarPct, color: C.ind }
              : null
        }
      />
      <KPICard
        label="Temperature"
        value={`${tempDisp}°C`}
        valueColor={tempTone || C.txtP}
        bar={tempNum != null ? { pct: (tempNum / 100) * 100, color: tempTone || C.info } : null}
      />
    </div>
  );
}
