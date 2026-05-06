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
  getPreset,
  wsConnect,
  startEvolutionWithPreset,
} from '../../config/api';
import LiveDot from '../shared/LiveDot';
import Badge from '../shared/Badge';
import { useToast } from '../../context/ToastContext';

const STEPS = ['Evaluate', 'Identify', 'Curate', 'Train', 'Compare', 'Decide', 'Record'];
const MAX_POINTS = 150;
const RECENT_OLLAMA_TAGS_KEY = 'modelforge_recent_ollama_tags';
const MAX_RECENT_OLLAMA_TAGS = 24;

function tagsFromModelListPayload(data) {
  const list = Array.isArray(data?.models) ? data.models : Array.isArray(data) ? data : [];
  return list.map((m) => m?.name || m?.model || m?.base_model || m?.id).filter(Boolean);
}

function rememberOllamaTag(tag) {
  const t = String(tag || '').trim();
  if (!t) return;
  try {
    const prev = JSON.parse(window.localStorage.getItem(RECENT_OLLAMA_TAGS_KEY) || '[]');
    const arr = Array.isArray(prev) ? prev : [];
    const next = [t, ...arr.filter((x) => x !== t)].slice(0, MAX_RECENT_OLLAMA_TAGS);
    window.localStorage.setItem(RECENT_OLLAMA_TAGS_KEY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
}

/** Map LangGraph `current_step` to dashboard step index. */
function apiStepToIndex(step) {
  const s = (step || '').toLowerCase();
  // Dashboard order: Evaluate → Identify → Curate → Train → Compare → Decide → Record
  if (['init_run', 'initialising', 'initializing', 'starting'].includes(s)) return 0;
  if (s === 'evaluate') return 0;
  if (s === 'identify_weaknesses') return 1;
  if (s === 'generate_training') return 2;
  if (s === 'train_adapter') return 3;
  if (s === 'compare_to_champion') return 4;
  if (s === 'promote_or_discard') return 5;
  if (['record', 'record_results', 'complete', 'completed'].includes(s)) return 6;
  return 0;
}

function formatElapsed(sec) {
  if (sec == null || Number.isNaN(sec)) return '00:00';
  const s = Math.floor(Number(sec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
}

/** Dashboard content scrolls inside `<main id="mf-dashboard-scroll">`, not the window — plain scrollIntoView often does nothing. */
function scrollToDashboardActivity() {
  const el = document.getElementById('activity-feed');
  const scroller = document.getElementById('mf-dashboard-scroll');
  if (el && scroller) {
    const top =
      scroller.scrollTop +
      (el.getBoundingClientRect().top - scroller.getBoundingClientRect().top) -
      16;
    scroller.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
    return;
  }
  el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

export default function EvolutionStatus() {
  const { show: toast } = useToast();
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
  /** Cached preset config bodies, keyed by preset name. Populated lazily so we
   * can show "Estimated time" and a one-line description without an extra
   * round-trip on every selection change. */
  const [presetDetails, setPresetDetails] = useState({});
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
  const [elapsedDisplaySeconds, setElapsedDisplaySeconds] = useState(0);
  const [completionMsg, setCompletionMsg] = useState(null);
  const [startError, setStartError] = useState(null);
  const [ollamaModels, setOllamaModels] = useState([]);
  /** When set, overrides preset `base_model` for `/api/evolve/start`. */
  const [presetBaseTag, setPresetBaseTag] = useState('');
  const [ollamaListError, setOllamaListError] = useState(false);
  const wsRef = useRef(null);
  const prevRunningRef = useRef(false);

  const loadOllamaModels = useCallback(async () => {
    setOllamaListError(false);
    const tags = new Set();
    const add = (arr) => {
      (arr || []).forEach((x) => {
        const s = String(x || '').trim();
        if (s) tags.add(s);
      });
    };

    let anySourceOk = false;

    const [rModels, rSys, rChamp] = await Promise.allSettled([
      apiFetch('/api/models'),
      apiFetch('/api/system/ollama-models'),
      apiFetch('/api/models/champion').catch(() => null),
    ]);

    if (rModels.status === 'fulfilled' && rModels.value) {
      add(tagsFromModelListPayload(rModels.value));
      anySourceOk = true;
    }
    if (rSys.status === 'fulfilled' && rSys.value?.models?.length) {
      add(rSys.value.models);
      anySourceOk = true;
    }
    if (rChamp.status === 'fulfilled' && rChamp.value) {
      const c = rChamp.value;
      if (c.ollama_model) add([c.ollama_model]);
      if (c.base_model) {
        const bm = String(c.base_model);
        if (!bm.includes('/')) add([bm]);
      }
      anySourceOk = true;
    }

    try {
      const raw = window.localStorage.getItem(RECENT_OLLAMA_TAGS_KEY);
      if (raw) add(JSON.parse(raw));
    } catch {
      /* ignore */
    }

    const sorted = [...tags].sort((a, b) => a.localeCompare(b));
    setOllamaModels(sorted);
    if (!sorted.length && !anySourceOk) {
      setOllamaListError(true);
    }
  }, []);

  const pullModel = useCallback(
    async (tag) => {
      const modelTag = String(tag || '').trim();
      if (!modelTag) return;
      try {
        await apiFetch('/api/models/pull', {
          method: 'POST',
          body: JSON.stringify({ model: modelTag }),
        });
        rememberOllamaTag(modelTag);
        toast(`Pull started for ${modelTag}`, 'success');
        await loadOllamaModels();
      } catch (e) {
        const status = e?.status ? ` (HTTP ${e.status})` : '';
        toast(`Failed to pull model${status}.`, 'danger');
      }
    },
    [loadOllamaModels, toast]
  );

  const isRunning = status.is_running === true || status.status === 'running';

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
    const iv = setInterval(fetchStatus, isRunning ? 2000 : 5000);
    return () => clearInterval(iv);
  }, [fetchStatus, isRunning]);

  // Keep the "Elapsed" display ticking smoothly between status polls (running only).
  useEffect(() => {
    if (status.elapsed_seconds != null && Number.isFinite(Number(status.elapsed_seconds))) {
      setElapsedDisplaySeconds(Number(status.elapsed_seconds));
    } else if (!isRunning) {
      setElapsedDisplaySeconds(0);
    }
  }, [status.elapsed_seconds, status.run_id, isRunning]);

  useEffect(() => {
    if (!isRunning) return undefined;
    const iv = setInterval(() => {
      setElapsedDisplaySeconds((s) => (Number.isFinite(s) ? s + 1 : 0));
    }, 1000);
    return () => clearInterval(iv);
  }, [isRunning, status.run_id]);

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

  useEffect(() => {
    if (!modalOpen) return;
    const onKey = (e) => {
      if (e.key === 'Escape') {
        setStartError(null);
        setModalOpen(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [modalOpen]);

  useEffect(() => {
    loadOllamaModels();
  }, [loadOllamaModels]);

  useEffect(() => {
    if (modalOpen) loadOllamaModels();
  }, [modalOpen, loadOllamaModels]);

  useEffect(() => {
    if (!modalOpen || tab !== 'custom' || !ollamaModels.length) return;
    setCustomCfg((c) =>
      ollamaModels.includes(c.base_model) ? c : { ...c, base_model: ollamaModels[0] }
    );
  }, [modalOpen, tab, ollamaModels]);

  // Lazy-fetch the selected preset's full config so the dialog can display
  // a 1-line description + estimated duration before the user commits.
  useEffect(() => {
    if (!modalOpen || tab !== 'preset' || !selectedPreset) return;
    if (presetDetails[selectedPreset]) return;
    let cancelled = false;
    (async () => {
      try {
        const p = await getPreset(selectedPreset);
        if (!cancelled && p?.config) {
          setPresetDetails((prev) => ({ ...prev, [selectedPreset]: p }));
        }
      } catch {
        /* ignore — fallback rendering handles the missing case */
      }
    })();
    return () => { cancelled = true; };
  }, [modalOpen, tab, selectedPreset, presetDetails]);

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
    const ws = wsConnect(`/api/ws/training/${status.run_id}`);
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

  // Completion messaging (detect transition running → idle).
  useEffect(() => {
    const wasRunning = prevRunningRef.current;
    prevRunningRef.current = isRunning;

    if (isRunning) {
      setCompletionMsg(null);
      return;
    }

    if (!wasRunning || !status.run_id || !(status.generation > 0)) return;

    let cancelled = false;
    (async () => {
      try {
        const rows = await apiFetch('/api/lineage/generations');
        const arr = Array.isArray(rows) ? rows : [];
        if (!arr.length) {
          if (!cancelled) setCompletionMsg({ message: '✅ Evolution complete' });
          return;
        }

        const latest = [...arr].sort((a, b) => (a.generation ?? 0) - (b.generation ?? 0)).pop();
        const genNum = latest?.generation ?? status.generation ?? 0;
        const promoted = !!latest?.promoted;

        const parentScores = latest?.parent_scores ?? {};
        const childScores = latest?.child_scores ?? {};
        const parentVals = Object.values(parentScores).filter((v) => typeof v === 'number');
        const childVals = Object.values(childScores).filter((v) => typeof v === 'number');
        const parentAvg = parentVals.length ? parentVals.reduce((a, b) => a + b, 0) / parentVals.length : null;
        const childAvg = childVals.length ? childVals.reduce((a, b) => a + b, 0) / childVals.length : null;

        const message = promoted
          ? `🏆 Gen ${genNum} is the new champion!`
          : `Gen ${genNum} discarded — parent was better`;

        if (!cancelled) setCompletionMsg({ message, promoted, genNum, parentAvg, childAvg });

        window.dispatchEvent(new Event('mf-dashboard-auto-refresh'));
      } catch {
        if (!cancelled) setCompletionMsg({ message: '✅ Evolution complete' });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [isRunning, status.run_id, status.generation]);

  const handleStartFromModal = async () => {
    setStartError(null);
    try {
      if (tab === 'preset') {
        if (!presets.length) {
          setStartError('No presets available — use Custom or check API / database.');
          return;
        }
        await startEvolutionWithPreset(
          selectedPreset,
          presetBaseTag ? { base_model: presetBaseTag } : {}
        );
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
              {formatElapsed(elapsedDisplaySeconds)}
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

        {completionMsg && !isRunning ? (
          <div
            style={{
              marginBottom: 14,
              padding: '10px 12px',
              borderRadius: 8,
              border: `1px solid ${
                completionMsg.promoted === true
                  ? 'rgba(34,197,94,0.35)'
                  : completionMsg.promoted === false
                    ? 'rgba(239,68,68,0.35)'
                    : 'rgba(129,140,248,0.35)'
              }`,
              background: completionMsg.promoted === true
                ? 'rgba(34,197,94,0.08)'
                : completionMsg.promoted === false
                  ? 'rgba(239,68,68,0.08)'
                  : 'rgba(129,140,248,0.08)',
              color: completionMsg.promoted === true ? C.acc : completionMsg.promoted === false ? C.danger : C.txtM,
              fontFamily: F.ui,
              fontSize: 13,
              lineHeight: 1.4,
            }}
          >
            {completionMsg.message}
            {completionMsg.parentAvg != null && completionMsg.childAvg != null ? (
              <div style={{ marginTop: 6, fontFamily: F.mono, fontSize: 12, color: C.txtS }}>
                Parent avg {completionMsg.parentAvg.toFixed(3)} · Child avg {completionMsg.childAvg.toFixed(3)}
              </div>
            ) : null}
          </div>
        ) : null}

        {isRunning ? (
          metrics.length > 0 ? (
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
          ) : (() => {
              // Better-than-spinner placeholder while we wait for the SFTTrainer
              // callback to publish its first loss to redis. The phase comes from
              // the orchestrator status so users see *what* is actually happening
              // (model download, curation, eval) instead of "Connecting…" forever.
              const stepKey = (status.current_step || '').toLowerCase();
              const phase = (() => {
                if (stepKey.includes('init')) return { label: 'Initialising run…', sub: 'Booting LangGraph orchestrator' };
                if (stepKey.includes('identify')) return { label: 'Identifying weaknesses…', sub: 'Reading champion benchmark gaps' };
                if (stepKey.includes('generate_training') || stepKey.includes('curate'))
                  return { label: 'Curating training data…', sub: 'Pulling targeted samples from HuggingFace' };
                if (stepKey.includes('train'))
                  return { label: 'Training LoRA adapter…', sub: 'Streaming `train_loss` from SFTTrainer' };
                if (stepKey.includes('evaluate') || stepKey.includes('compare'))
                  return { label: 'Evaluating across benchmarks…', sub: 'lm-eval mmlu · arc · hellaswag · gsm8k · humaneval' };
                if (stepKey.includes('promote') || stepKey.includes('decide') || stepKey.includes('record'))
                  return { label: 'Promoting / recording…', sub: 'Writing generation to Postgres' };
                return { label: 'Working…', sub: 'Run is healthy — first metric incoming' };
              })();
              const elapsedMin = Math.floor(elapsedDisplaySeconds / 60);
              const elapsedSec = elapsedDisplaySeconds % 60;
              return (
                <div style={{ marginBottom: 16, padding: '14px 4px' }}>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      marginBottom: 10,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <LiveDot color={C.ind} />
                      <span style={{ fontFamily: F.ui, fontSize: 13, color: C.txtP, fontWeight: 600 }}>
                        {phase.label}
                      </span>
                    </div>
                    <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM }}>
                      {String(elapsedMin).padStart(2, '0')}:{String(elapsedSec).padStart(2, '0')}
                      {tokensPerSec != null ? ` · ${tokensPerSec.toFixed(0)} tok/s` : ''}
                    </span>
                  </div>
                  <div style={{ fontFamily: F.ui, fontSize: 11, color: C.txtM, marginBottom: 12 }}>
                    {phase.sub}
                  </div>
                  {/* Indeterminate striped progress bar — gives the user something to watch
                      while we wait for the first concrete metric (loss / score) to arrive. */}
                  <div
                    style={{
                      position: 'relative',
                      height: 6,
                      borderRadius: 3,
                      overflow: 'hidden',
                      background: 'rgba(129,140,248,0.10)',
                      border: `1px solid ${C.border}`,
                    }}
                  >
                    <div
                      style={{
                        position: 'absolute',
                        inset: 0,
                        backgroundImage: `repeating-linear-gradient(45deg, ${C.ind}55 0 8px, transparent 8px 16px)`,
                        animation: 'mf-bar-stripes 1.4s linear infinite',
                      }}
                    />
                  </div>
                </div>
              );
            })()
        ) : null}

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
                    animation: active ? 'mf-pulse 1.4s ease-in-out infinite' : 'none',
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
            title="Scroll to the Activity panel — DB-backed evolution events. (raw API logs: docker compose logs api)"
            onClick={() => scrollToDashboardActivity()}
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
            View activity
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
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <label style={{ display: 'block' }}>
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

                {(() => {
                  const detail = presetDetails[selectedPreset];
                  const cfg = detail?.config || {};
                  // Rough ETA per generation. Empirically: TinyLlama ~12 min,
                  // 3B Llama ~25 min, 8B Llama ~75 min for ~3000 samples.
                  // Adjust by max_samples / 3000.
                  const sizeMin = (() => {
                    const bm = String(cfg.base_model || '').toLowerCase();
                    if (bm.includes('tinyllama') || bm.includes('1b')) return 12;
                    if (bm.includes('3b')) return 25;
                    if (bm.includes('8b')) return 75;
                    if (bm.includes('70b')) return 600;
                    return 30;
                  })();
                  const samples = Number(cfg.max_samples) || 3000;
                  const perGen = Math.round(sizeMin * (samples / 3000));
                  const totalMin = perGen * Number(cfg.max_generations || 1);
                  const fmtEta = (m) => {
                    if (m < 60) return `~${m} min`;
                    const h = Math.floor(m / 60);
                    const r = m % 60;
                    return r ? `~${h}h ${r}m` : `~${h}h`;
                  };

                  // Static one-line descriptions for the built-in presets.
                  const blurb = {
                    'quick-test': 'Smoke test — 1-2 generations, small samples, fast feedback.',
                    'standard': 'Default loop — 10 generations on full benchmarks.',
                    'deep-evolution': 'Long run — many generations, broad benchmarks (≈half a day).',
                    'reasoning-specialist': 'Targets reasoning benchmarks (mmlu, arc, gsm8k).',
                    'code-specialist': 'Targets code benchmarks (humaneval).',
                  }[selectedPreset];

                  return (
                    <div
                      style={{
                        padding: '10px 12px',
                        background: 'rgba(118,185,0,0.06)',
                        border: `1px solid rgba(118,185,0,0.20)`,
                        borderRadius: 8,
                        fontFamily: F.ui,
                        fontSize: 12,
                        color: C.txtS,
                        lineHeight: 1.55,
                      }}
                    >
                      {blurb ? (
                        <div style={{ color: C.txtP, marginBottom: detail ? 6 : 0 }}>{blurb}</div>
                      ) : null}
                      {detail ? (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, fontFamily: F.mono, color: C.txtM, fontSize: 11 }}>
                          <span>base: <span style={{ color: C.acc }}>{cfg.base_model || '—'}</span></span>
                          <span>·</span>
                          <span>{cfg.max_generations ?? '?'} gen</span>
                          <span>·</span>
                          <span>{(cfg.max_samples ?? '?').toLocaleString?.() ?? cfg.max_samples ?? '?'} samples</span>
                          <span>·</span>
                          <span>LoRA r={cfg.lora_rank ?? '?'}</span>
                          <span>·</span>
                          <span style={{ color: C.acc }}>est. {fmtEta(totalMin)}</span>
                        </div>
                      ) : (
                        <div style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM }}>
                          loading preset…
                        </div>
                      )}
                    </div>
                  );
                })()}
                <label style={{ display: 'block' }}>
                  <span style={{ fontSize: 11, color: C.txtM, fontFamily: F.ui }}>
                    Base Ollama model (optional)
                  </span>
                  <div style={{ marginTop: 6, display: 'flex', gap: 8, alignItems: 'center' }}>
                    {ollamaModels.length ? (
                      <select
                        value={presetBaseTag}
                        onChange={(e) => setPresetBaseTag(e.target.value)}
                        style={{
                          flex: 1,
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
                        <option value="">Use preset default</option>
                        {ollamaModels.map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type="text"
                        value={presetBaseTag}
                        onChange={(e) => setPresetBaseTag(e.target.value)}
                        placeholder="e.g. llama3.2:3b"
                        style={{
                          flex: 1,
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
                    )}
                    <button
                      type="button"
                      onClick={() => {
                        const tag = window.prompt('Enter Ollama model tag (e.g. llama3.2:3b)');
                        if (tag) pullModel(tag);
                      }}
                      style={{
                        padding: '8px 10px',
                        borderRadius: 6,
                        border: `1px solid ${C.border}`,
                        background: C.bgE,
                        color: C.txtS,
                        cursor: 'pointer',
                        fontFamily: F.ui,
                        fontSize: 12,
                        whiteSpace: 'nowrap',
                      }}
                    >
                      Pull Model
                    </button>
                  </div>
                  {!ollamaModels.length ? (
                    <p style={{ fontSize: 10, color: C.txtM, fontFamily: F.ui, margin: '8px 0 0 0', lineHeight: 1.45 }}>
                      {ollamaListError
                        ? 'API could not list Ollama tags — if Ollama runs on this machine, ensure it listens on 0.0.0.0:11434 and the API container uses OLLAMA_HOST=http://host.docker.internal:11434 (see docker-compose / .env).'
                        : 'No models listed yet — type a tag, pull one, or open the modal again after the API can reach Ollama.'}
                    </p>
                  ) : null}
                </label>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <label style={{ fontSize: 11, color: C.txtM, fontFamily: F.ui }}>
                  Base Ollama model
                  {ollamaModels.length > 0 ? (
                    <div style={{ marginTop: 4, display: 'flex', gap: 8, alignItems: 'center' }}>
                      <select
                        value={customCfg.base_model}
                        onChange={(e) =>
                          setCustomCfg((c) => ({ ...c, base_model: e.target.value }))
                        }
                        style={{
                          flex: 1,
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
                        {customCfg.base_model &&
                        !ollamaModels.includes(customCfg.base_model) ? (
                          <option value={customCfg.base_model}>
                            {customCfg.base_model} (manual)
                          </option>
                        ) : null}
                        {ollamaModels.map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        onClick={() => {
                          const tag = window.prompt('Enter Ollama model tag (e.g. llama3.2:3b)');
                          if (tag) pullModel(tag);
                        }}
                        style={{
                          padding: '8px 10px',
                          borderRadius: 6,
                          border: `1px solid ${C.border}`,
                          background: C.bgE,
                          color: C.txtS,
                          cursor: 'pointer',
                          fontFamily: F.ui,
                          fontSize: 12,
                          whiteSpace: 'nowrap',
                        }}
                      >
                        Pull Model
                      </button>
                    </div>
                  ) : (
                    <>
                      <input
                        type="text"
                        value={customCfg.base_model ?? ''}
                        onChange={(e) =>
                          setCustomCfg((c) => ({ ...c, base_model: e.target.value }))
                        }
                        placeholder="e.g. llama3.2:3b"
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
                      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
                        <button
                          type="button"
                          onClick={() => {
                            const tag = window.prompt('Enter Ollama model tag (e.g. llama3.2:3b)');
                            if (tag) pullModel(tag);
                          }}
                          style={{
                            padding: '8px 10px',
                            borderRadius: 6,
                            border: `1px solid ${C.border}`,
                            background: C.bgE,
                            color: C.txtS,
                            cursor: 'pointer',
                            fontFamily: F.ui,
                            fontSize: 12,
                            whiteSpace: 'nowrap',
                          }}
                        >
                          Pull Model
                        </button>
                      </div>
                      <p style={{ fontSize: 10, color: C.txtM, fontFamily: F.ui, margin: '8px 0 0 0', lineHeight: 1.45 }}>
                        No models from Ollama yet — you can type one manually, or pull a new one.
                      </p>
                    </>
                  )}
                </label>
                {[
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
