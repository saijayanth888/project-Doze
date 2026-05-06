import { useEffect, useState, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useSearchParams } from 'react-router-dom';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { C, F } from '../../config/colors';
import {
  apiFetch,
  fetchPresets,
  wsConnect,
  startEvolutionWithPreset,
} from '../../config/api';
import LiveDot from '../shared/LiveDot';
import Badge from '../shared/Badge';

const STEPS = ['Evaluate', 'Identify', 'Curate', 'Train', 'Compare', 'Decide', 'Record'];
const MAX_POINTS = 150;

/** Map LangGraph `current_step` to dashboard step index. */
function apiStepToIndex(step) {
  const s = (step || '').toLowerCase();
  if (s === 'init_run' || s === 'starting') return 0;
  if (s === 'identify_weaknesses') return 1;
  if (s === 'generate_training') return 2;
  if (s === 'train_adapter') return 3;
  if (s === 'evaluate') return 4;
  if (s === 'compare_to_champion') return 4;
  if (s === 'promote_or_discard') return 5;
  return 0;
}

function formatElapsed(sec) {
  if (sec == null || Number.isNaN(sec)) return '00:00';
  const s = Math.floor(Number(sec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
}

export default function EvolutionStatus() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [status, setStatus] = useState({
    status: 'idle',
    is_running: false,
    generation: 0,
    current_step: null,
    run_id: null,
    config: {},
    elapsed_seconds: null,
  });
  const [presets, setPresets] = useState([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [tab, setTab] = useState('preset');
  const [selectedPreset, setSelectedPreset] = useState('standard');
  const [customCfg, setCustomCfg] = useState({
    base_model: 'llama3.2:3b',
    max_generations: 10,
    lora_rank: 16,
    lora_alpha: 32,
    learning_rate: 0.0002,
    batch_size: 2,
    custom_dataset_id: '',
    max_samples: 3000,
  });
  const [metrics, setMetrics] = useState([]);
  const [tokensPerSec, setTokensPerSec] = useState(null);
  const [startError, setStartError] = useState(null);
  const wsRef = useRef(null);

  const fetchStatus = useCallback(async () => {
    try {
      const d = await apiFetch('/api/evolve/status');
      setStatus((prev) => ({
        ...prev,
        ...d,
        status: d.status ?? prev.status,
        generation: d.generation ?? 0,
      }));
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const iv = setInterval(fetchStatus, 3000);
    return () => clearInterval(iv);
  }, [fetchStatus]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const p = await fetchPresets();
        if (!cancelled && p?.presets?.length) {
          setPresets(p.presets);
          const names = p.presets.map((x) => x.name);
          if (names.includes('standard')) setSelectedPreset('standard');
          else setSelectedPreset(p.presets[0].name);
        } else if (!cancelled) {
          setTab('custom');
        }
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const presetFromUrl = searchParams.get('preset');
  const startEvolutionFromUrl = searchParams.get('startEvolution');

  /** Deep-link from sidebar (`?startEvolution=1`) or preset promotion (`?preset=name`). */
  useEffect(() => {
    const openEvolution =
      startEvolutionFromUrl === '1' || startEvolutionFromUrl === 'true';
    if (!presetFromUrl && !openEvolution) return;

    if (presetFromUrl) {
      setSelectedPreset(presetFromUrl);
      setTab('preset');
      setModalOpen(true);
    }
    if (openEvolution) {
      setModalOpen(true);
    }

    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (presetFromUrl) next.delete('preset');
        if (openEvolution) next.delete('startEvolution');
        return next;
      },
      { replace: true }
    );
  }, [presetFromUrl, startEvolutionFromUrl, setSearchParams]);

  const isRunning = status.is_running === true || status.status === 'running';

  const idleNoRun =
    !isRunning &&
    (status.status === 'idle' || !status.status) &&
    (status.generation === 0 || status.generation == null) &&
    !status.run_id;

  useEffect(() => {
    if (!isRunning || !status.run_id) {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      return;
    }

    setMetrics([]);
    const ws = wsConnect(`/ws/training/${status.run_id}`);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.event === 'done') {
          return;
        }
        if (typeof data.loss === 'number') {
          setTokensPerSec(data.tokens_per_sec ?? null);
          setMetrics((prev) => {
            const next = [
              ...prev,
              {
                step: data.step,
                loss: data.loss,
                lr: data.lr,
                epoch: data.epoch,
                tokens_per_sec: data.tokens_per_sec,
              },
            ];
            return next.slice(-MAX_POINTS);
          });
        }
      } catch {
        /* ignore */
      }
    };
    ws.onerror = () => {};
    return () => {
      ws.close();
      if (wsRef.current === ws) wsRef.current = null;
    };
  }, [isRunning, status.run_id]);

  const stepIndex = apiStepToIndex(status.current_step);

  const handleStartFromModal = async () => {
    setStartError(null);
    try {
      if (tab === 'preset') {
        if (!presets.length) {
          setStartError('No presets available — use Custom or check API / database.');
          return;
        }
        await startEvolutionWithPreset(selectedPreset);
      } else {
        const body = { ...customCfg };
        if (!body.custom_dataset_id) delete body.custom_dataset_id;
        if (body.max_samples == null) delete body.max_samples;
        await apiFetch('/api/evolve/start', {
          method: 'POST',
          body: JSON.stringify(body),
        });
      }
      setModalOpen(false);
      setMetrics([]);
      fetchStatus();
    } catch (e) {
      const detail = e?.body?.detail;
      const msg =
        typeof detail === 'string'
          ? detail
          : Array.isArray(detail)
            ? detail.map((x) => x.msg || JSON.stringify(x)).join('; ')
            : e?.message || 'Request failed';
      setStartError(msg);
    }
  };

  const handleStop = async () => {
    try {
      if (status.run_id) {
        await apiFetch(`/api/evolve/${status.run_id}/stop`, { method: 'POST' });
      }
      fetchStatus();
    } catch {
      /* ignore */
    }
  };

  const cfg = status.config || {};
  const cfgStrip = [
    ['base', cfg.base_model],
    ['max gen', cfg.max_generations],
    ['LoRA r', cfg.lora_rank],
    ['LR', cfg.learning_rate],
  ]
    .filter(([, v]) => v != null && v !== '')
    .map(([k, v]) => `${k}: ${v}`)
    .join('  ·  ');

  return (
    <div
      data-testid="evolution-status-panel"
      className="mf-card-hover"
      style={{
        background: C.bgC,
        border: `1px solid ${C.border}`,
        borderRadius: 8,
        padding: 20,
        position: 'relative',
        overflow: 'hidden',
        height: '100%',
      }}
    >
      {isRunning && (
        <div
          aria-hidden
          style={{
            position: 'absolute',
            inset: 0,
            borderRadius: 8,
            zIndex: 0,
            padding: 1,
            pointerEvents: 'none',
            background:
              'conic-gradient(from var(--evolution-angle),#818cf8,#c084fc,#f472b6,#818cf8)',
            animation: 'evolution-spin 3s linear infinite',
          }}
        >
          <div
            style={{
              position: 'absolute',
              inset: 1,
              background: C.bgC,
              borderRadius: 7,
            }}
          />
        </div>
      )}
      <div style={{ position: 'relative', zIndex: 1, pointerEvents: 'auto' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 12,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {isRunning && <LiveDot />}
            <span
              style={{
                fontFamily: F.ui,
                fontSize: 13,
                fontWeight: 700,
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                color: C.txtM,
              }}
            >
              Evolution Status
            </span>
          </div>
          <Badge type={isRunning ? 'running' : 'idle'}>{isRunning ? 'Running' : 'Idle'}</Badge>
        </div>

        {cfgStrip ? (
          <div
            style={{
              fontFamily: F.mono,
              fontSize: 10,
              color: C.txtS,
              marginBottom: 14,
              lineHeight: 1.5,
              wordBreak: 'break-word',
            }}
          >
            {cfgStrip}
          </div>
        ) : null}

        <div style={{ display: 'flex', gap: 32, marginBottom: 20 }}>
          <div style={{ flex: '1 1 40%', minWidth: 0 }}>
            <div
              style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: '0.1em',
                textTransform: 'uppercase',
                color: C.txtM,
                marginBottom: 4,
              }}
            >
              Generation
            </div>
            {idleNoRun ? (
              <p
                style={{
                  fontFamily: F.ui,
                  fontSize: 13,
                  color: C.txtM,
                  lineHeight: 1.5,
                  margin: '4px 0 0 0',
                  maxWidth: 320,
                }}
              >
                No evolution run yet — click Start Evolution to begin.
              </p>
            ) : (
              <div
                style={{
                  fontFamily: F.mono,
                  fontSize: '3rem',
                  fontWeight: 500,
                  color: C.txtP,
                  lineHeight: 1,
                }}
              >
                {status.generation}
              </div>
            )}
          </div>
          <div>
            <div
              style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: '0.1em',
                textTransform: 'uppercase',
                color: C.txtM,
                marginBottom: 4,
              }}
            >
              Elapsed
            </div>
            <div
              style={{
                fontFamily: F.mono,
                fontSize: '3rem',
                fontWeight: 500,
                color: isRunning ? C.acc : C.txtM,
                lineHeight: 1,
              }}
            >
              {formatElapsed(status.elapsed_seconds)}
            </div>
          </div>
          {status.run_id && (
            <div>
              <div
                style={{
                  fontSize: 9,
                  fontWeight: 700,
                  letterSpacing: '0.1em',
                  textTransform: 'uppercase',
                  color: C.txtM,
                  marginBottom: 4,
                }}
              >
                Run ID
              </div>
              <div
                style={{
                  fontFamily: F.mono,
                  fontSize: 13,
                  color: C.txtS,
                  marginTop: 10,
                }}
              >
                {status.run_id}
              </div>
            </div>
          )}
        </div>

        {isRunning && metrics.length > 0 && (
          <div style={{ marginBottom: 16, height: 160 }}>
            <div
              style={{
                fontSize: 10,
                color: C.txtM,
                fontFamily: F.mono,
                marginBottom: 6,
                display: 'flex',
                justifyContent: 'space-between',
              }}
            >
              <span>Training loss</span>
              {tokensPerSec != null && (
                <span style={{ color: C.acc }}>
                  {tokensPerSec.toFixed(0)} tok/s
                </span>
              )}
            </div>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={metrics}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
                <XAxis dataKey="step" stroke={C.txtM} tick={{ fontSize: 10 }} />
                <YAxis stroke={C.txtM} tick={{ fontSize: 10 }} width={40} />
                <Tooltip
                  contentStyle={{
                    background: C.bgI,
                    border: `1px solid ${C.border}`,
                    fontSize: 11,
                  }}
                />
                <Line type="monotone" dataKey="loss" stroke={C.ind} dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        <div style={{ display: 'flex', gap: 0, marginBottom: 16, position: 'relative' }}>
          <div
            style={{
              position: 'absolute',
              top: 14,
              left: 14,
              right: 14,
              height: 1,
              background: C.border,
              zIndex: 0,
            }}
          />
          {STEPS.map((step, i) => {
            const done = i < stepIndex;
            const active = i === stepIndex && isRunning;
            return (
              <div
                key={step}
                style={{
                  flex: 1,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: 6,
                  position: 'relative',
                  zIndex: 1,
                }}
              >
                <div
                  style={{
                    width: 28,
                    height: 28,
                    borderRadius: '50%',
                    background: done ? C.accDim : active ? 'rgba(118,185,0,0.2)' : C.bgC,
                    border: `2px solid ${done || active ? C.acc : C.border}`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    boxShadow: active ? `0 0 12px ${C.accGlow}` : 'none',
                  }}
                >
                  {done ? (
                    <svg
                      width="11"
                      height="11"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke={C.acc}
                      strokeWidth="3"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <polyline points="20,6 9,17 4,12" />
                    </svg>
                  ) : active ? (
                    <LiveDot color={C.acc} />
                  ) : null}
                </div>
                <span
                  style={{
                    fontSize: 10,
                    color: active ? C.txtP : done ? C.acc : C.txtM,
                    fontFamily: F.ui,
                    fontWeight: active ? 600 : 400,
                    textAlign: 'center',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {step}
                </span>
              </div>
            );
          })}
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {isRunning ? (
            <button
              type="button"
              onClick={handleStop}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 5,
                padding: '5px 12px',
                background: C.dangerDim,
                color: C.danger,
                border: '1px solid rgba(239,68,68,0.3)',
                borderRadius: 4,
                cursor: 'pointer',
                fontFamily: F.ui,
                fontSize: 12,
                fontWeight: 600,
              }}
            >
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <rect x="3" y="3" width="18" height="18" rx="2" />
              </svg>
              Stop Run
            </button>
          ) : (
            <button
              type="button"
              className="mf-cta-primary"
              onClick={() => {
                setStartError(null);
                setModalOpen(true);
              }}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 5,
                padding: '5px 12px',
                background: C.acc,
                color: '#000',
                border: 'none',
                borderRadius: 4,
                cursor: 'pointer',
                fontFamily: F.ui,
                fontSize: 12,
                fontWeight: 700,
                boxShadow: `0 0 12px ${C.accGlow}`,
              }}
            >
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <polygon points="5,3 19,12 5,21" />
              </svg>
              Start Evolution
            </button>
          )}
          <button
            type="button"
            onClick={() => document.getElementById('activity-feed')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
            style={{
              padding: '5px 12px',
              background: 'transparent',
              color: C.txtS,
              border: `1px solid ${C.border}`,
              borderRadius: 4,
              cursor: 'pointer',
              fontFamily: F.ui,
              fontSize: 12,
            }}
          >
            View Logs
          </button>
        </div>
      </div>

      {modalOpen &&
        typeof document !== 'undefined' &&
        createPortal(
          <div
            style={{
              position: 'fixed',
              inset: 0,
              background: 'rgba(0,0,0,0.55)',
              zIndex: 10000,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 16,
            }}
            role="presentation"
            onClick={() => {
              setStartError(null);
              setModalOpen(false);
            }}
          >
            <div
              role="dialog"
              aria-modal="true"
              onClick={(e) => e.stopPropagation()}
              style={{
                background: C.bgC,
                border: `1px solid ${C.border}`,
                borderRadius: 10,
                padding: 20,
                maxWidth: 440,
                width: '100%',
                maxHeight: '90vh',
                overflow: 'auto',
              }}
            >
            <div style={{ fontFamily: F.ui, fontWeight: 700, color: C.txtP, marginBottom: 12 }}>
              Start evolution
            </div>
            {startError ? (
              <div
                role="alert"
                style={{
                  marginBottom: 12,
                  padding: '8px 10px',
                  borderRadius: 6,
                  background: 'rgba(239,68,68,0.12)',
                  border: '1px solid rgba(239,68,68,0.35)',
                  color: C.danger,
                  fontFamily: F.ui,
                  fontSize: 12,
                  lineHeight: 1.45,
                }}
              >
                {startError}
              </div>
            ) : null}
            <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
              {['preset', 'custom'].map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTab(t)}
                  style={{
                    flex: 1,
                    padding: '8px 0',
                    borderRadius: 6,
                    border: `1px solid ${tab === t ? C.acc : C.border}`,
                    background: tab === t ? C.accDim : 'transparent',
                    color: tab === t ? C.acc : C.txtS,
                    fontFamily: F.ui,
                    fontSize: 12,
                    cursor: 'pointer',
                    textTransform: 'capitalize',
                  }}
                >
                  {t}
                </button>
              ))}
            </div>
            {tab === 'preset' ? (
              <label style={{ display: 'block', marginBottom: 12 }}>
                <span style={{ fontSize: 11, color: C.txtM, fontFamily: F.ui }}>Preset</span>
                <select
                  value={selectedPreset}
                  onChange={(e) => setSelectedPreset(e.target.value)}
                  style={{
                    marginTop: 6,
                    width: '100%',
                    padding: '8px 10px',
                    background: C.bgI,
                    border: `1px solid ${C.border}`,
                    borderRadius: 6,
                    color: C.txtP,
                    fontFamily: F.mono,
                    fontSize: 12,
                  }}
                >
                  {presets.map((p) => (
                    <option key={p.name} value={p.name}>
                      {p.name}
                      {p.is_builtin ? ' (built-in)' : ''}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {[
                  ['base_model', 'Base model'],
                  ['max_generations', 'Max generations', 'number'],
                  ['lora_rank', 'LoRA rank', 'number'],
                  ['lora_alpha', 'LoRA alpha', 'number'],
                  ['learning_rate', 'Learning rate', 'number'],
                  ['batch_size', 'Batch size', 'number'],
                  ['max_samples', 'Max samples', 'number'],
                  ['custom_dataset_id', 'Custom dataset ID (optional)'],
                ].map(([key, label, type]) => (
                  <label key={key} style={{ fontSize: 11, color: C.txtM, fontFamily: F.ui }}>
                    {label}
                    <input
                      type={type || 'text'}
                      value={
                        key === 'learning_rate'
                          ? String(customCfg.learning_rate)
                          : customCfg[key] ?? ''
                      }
                      onChange={(e) =>
                        setCustomCfg((c) => ({
                          ...c,
                          [key]:
                            type === 'number'
                              ? key === 'learning_rate'
                                ? parseFloat(e.target.value) || 0
                                : parseInt(e.target.value, 10) || 0
                              : e.target.value,
                        }))
                      }
                      style={{
                        marginTop: 4,
                        width: '100%',
                        padding: '8px 10px',
                        background: C.bgI,
                        border: `1px solid ${C.border}`,
                        borderRadius: 6,
                        color: C.txtP,
                        fontFamily: F.mono,
                        fontSize: 12,
                      }}
                    />
                  </label>
                ))}
              </div>
            )}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
                <button
                  type="button"
                  onClick={() => {
                    setStartError(null);
                    setModalOpen(false);
                  }}
                  style={{
                  padding: '8px 14px',
                  background: 'transparent',
                  border: `1px solid ${C.border}`,
                  borderRadius: 6,
                  color: C.txtS,
                  cursor: 'pointer',
                  fontFamily: F.ui,
                  fontSize: 12,
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleStartFromModal}
                style={{
                  padding: '8px 14px',
                  background: C.acc,
                  border: 'none',
                  borderRadius: 6,
                  color: '#000',
                  fontWeight: 700,
                  cursor: 'pointer',
                  fontFamily: F.ui,
                  fontSize: 12,
                }}
              >
                Start
              </button>
            </div>
          </div>
        </div>,
          document.body
        )}
    </div>
  );
}
