import { useEffect, useState } from 'react';
import { C, F } from '../../config/colors';
import { apiFetch } from '../../config/api';
import LiveDot from '../shared/LiveDot';
import Badge from '../shared/Badge';

const STEPS = ['Evaluate', 'Identify', 'Curate', 'Train', 'Compare', 'Decide', 'Record'];

export default function EvolutionStatus() {
  const [status, setStatus] = useState({ status: 'idle', generation: 0, current_step: null, run_id: null });
  const [elapsed, setElapsed] = useState('00:00');

  useEffect(() => {
    const fetch = async () => {
      try {
        const d = await apiFetch('/api/evolve/status');
        setStatus(d);
      } catch {}
    };
    fetch();
    const iv = setInterval(fetch, 3000);
    return () => clearInterval(iv);
  }, []);

  const isRunning = status.status === 'running';
  const stepIndex = STEPS.findIndex(s => s.toLowerCase() === status.current_step?.toLowerCase());

  const handleStart = async () => {
    try {
      await apiFetch('/api/evolve/start', { method: 'POST', body: JSON.stringify({}) });
    } catch {}
  };
  const handleStop = async () => {
    try {
      if (status.run_id) await apiFetch(`/api/evolve/${status.run_id}/stop`, { method: 'POST' });
    } catch {}
  };

  return (
    <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 20, position: 'relative', overflow: 'hidden', height: '100%' }}>
      {isRunning && (
        <div style={{ position: 'absolute', inset: 0, borderRadius: 8, zIndex: 0, padding: 1,
          background: 'conic-gradient(from var(--evolution-angle),#818cf8,#c084fc,#f472b6,#818cf8)',
          animation: 'evolution-spin 3s linear infinite' }}>
          <div style={{ position: 'absolute', inset: 1, background: C.bgC, borderRadius: 7 }} />
        </div>
      )}
      <div style={{ position: 'relative', zIndex: 1 }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {isRunning && <LiveDot />}
            <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.txtM }}>Evolution Status</span>
          </div>
          <Badge type={isRunning ? 'running' : 'idle'}>{isRunning ? 'Running' : 'Idle'}</Badge>
        </div>

        {/* Big numbers */}
        <div style={{ display: 'flex', gap: 32, marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: C.txtM, marginBottom: 4 }}>Generation</div>
            <div style={{ fontFamily: F.mono, fontSize: '3rem', fontWeight: 500, color: C.txtP, lineHeight: 1 }}>{status.generation}</div>
          </div>
          <div>
            <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: C.txtM, marginBottom: 4 }}>Elapsed</div>
            <div style={{ fontFamily: F.mono, fontSize: '3rem', fontWeight: 500, color: isRunning ? C.acc : C.txtM, lineHeight: 1 }}>{elapsed}</div>
          </div>
          {status.run_id && (
            <div>
              <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: C.txtM, marginBottom: 4 }}>Run ID</div>
              <div style={{ fontFamily: F.mono, fontSize: 13, color: C.txtS, marginTop: 10 }}>{status.run_id}</div>
            </div>
          )}
        </div>

        {/* Steps */}
        <div style={{ display: 'flex', gap: 0, marginBottom: 16, position: 'relative' }}>
          <div style={{ position: 'absolute', top: 14, left: 14, right: 14, height: 1, background: C.border, zIndex: 0 }} />
          {STEPS.map((step, i) => {
            const done = i < stepIndex;
            const active = i === stepIndex && isRunning;
            return (
              <div key={step} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, position: 'relative', zIndex: 1 }}>
                <div style={{
                  width: 28, height: 28, borderRadius: '50%',
                  background: done ? C.accDim : active ? 'rgba(118,185,0,0.2)' : C.bgC,
                  border: `2px solid ${done || active ? C.acc : C.border}`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  boxShadow: active ? `0 0 12px ${C.accGlow}` : 'none',
                }}>
                  {done
                    ? <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke={C.acc} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20,6 9,17 4,12"/></svg>
                    : active ? <LiveDot color={C.acc} /> : null}
                </div>
                <span style={{ fontSize: 10, color: active ? C.txtP : done ? C.acc : C.txtM, fontFamily: F.ui, fontWeight: active ? 600 : 400, textAlign: 'center', whiteSpace: 'nowrap' }}>{step}</span>
              </div>
            );
          })}
        </div>

        {/* Controls */}
        <div style={{ display: 'flex', gap: 8 }}>
          {isRunning ? (
            <button onClick={handleStop} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '5px 12px', background: C.dangerDim, color: C.danger, border: `1px solid rgba(239,68,68,0.3)`, borderRadius: 4, cursor: 'pointer', fontFamily: F.ui, fontSize: 12, fontWeight: 600 }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><rect x="3" y="3" width="18" height="18" rx="2"/></svg>
              Stop Run
            </button>
          ) : (
            <button onClick={handleStart} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '5px 12px', background: C.acc, color: '#000', border: 'none', borderRadius: 4, cursor: 'pointer', fontFamily: F.ui, fontSize: 12, fontWeight: 700 }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polygon points="5,3 19,12 5,21"/></svg>
              Start Evolution
            </button>
          )}
          <button style={{ padding: '5px 12px', background: 'transparent', color: C.txtS, border: `1px solid ${C.border}`, borderRadius: 4, cursor: 'pointer', fontFamily: F.ui, fontSize: 12 }}>
            View Logs
          </button>
        </div>
      </div>
    </div>
  );
}
