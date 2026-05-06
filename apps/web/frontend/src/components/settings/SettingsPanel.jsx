import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Eye, EyeOff, Save, Trash2, Sparkles, HardDrive, Clock } from 'lucide-react';
import { C, F } from '../../config/colors';
import {
  fetchPresets,
  savePreset,
  deletePreset,
  fetchAdapters,
  cleanupAdapters,
} from '../../config/api';
import MagneticButton from '../shared/MagneticButton';

const AUTOSCHEDULE_KEY = 'mf_autoschedule';

function Section({ title, children }) {
  return (
    <div style={{
      background: '#111827',
      border: '1px solid #1e293b',
      borderRadius: 12,
      padding: 20,
      marginBottom: 16,
    }}>
      <div style={{ fontSize: 11, color: '#64748b', fontFamily: 'JetBrains Mono', letterSpacing: 2, marginBottom: 14 }}>
        {title}
      </div>
      {children}
    </div>
  );
}

function Slider({ label, value, onChange, min = 0, max = 100, step = 1, unit = '' }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <label style={{ fontSize: 13, color: '#94a3b8', fontFamily: 'Outfit' }}>{label}</label>
        <span style={{ fontSize: 12, fontFamily: 'JetBrains Mono', color: '#76b900' }}>{value}{unit}</span>
      </div>
      <input
        type="range"
        min={min} max={max} step={step}
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        style={{ width: '100%', accentColor: '#76b900', cursor: 'pointer' }}
      />
    </div>
  );
}

function Toggle({ label, value, onChange, description }) {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      padding: '10px 0',
      borderBottom: '1px solid rgba(30,41,59,0.5)',
    }}>
      <div>
        <div style={{ fontSize: 13, color: '#94a3b8', fontFamily: 'Outfit' }}>{label}</div>
        {description && <div style={{ fontSize: 11, color: '#475569', fontFamily: 'Outfit', marginTop: 2 }}>{description}</div>}
      </div>
      <button
        onClick={() => onChange(!value)}
        style={{
          width: 40, height: 22,
          borderRadius: 11,
          border: 'none',
          background: value ? '#76b900' : '#1e293b',
          cursor: 'pointer',
          position: 'relative',
          transition: 'background 200ms',
          flexShrink: 0,
        }}
      >
        <span style={{
          position: 'absolute',
          top: 3, left: value ? 20 : 3,
          width: 16, height: 16,
          borderRadius: '50%',
          background: '#fff',
          transition: 'left 200ms',
        }} />
      </button>
    </div>
  );
}

function ApiKey({ label, value, onChange }) {
  const [visible, setVisible] = useState(false);
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{ fontSize: 12, color: '#64748b', fontFamily: 'Outfit', display: 'block', marginBottom: 6 }}>
        {label}
      </label>
      <div style={{ position: 'relative' }}>
        <input
          type={visible ? 'text' : 'password'}
          value={value}
          onChange={e => onChange(e.target.value)}
          style={{
            width: '100%',
            background: '#0c1018',
            border: '1px solid #1e293b',
            borderRadius: 8,
            padding: '8px 36px 8px 12px',
            color: '#94a3b8',
            fontFamily: 'JetBrains Mono',
            fontSize: 13,
            outline: 'none',
          }}
        />
        <button
          onClick={() => setVisible(v => !v)}
          style={{
            position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)',
            background: 'none', border: 'none', cursor: 'pointer', color: '#64748b',
          }}
        >
          {visible ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      </div>
    </div>
  );
}

function Select({ label, value, onChange, options }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{ fontSize: 12, color: '#64748b', fontFamily: 'Outfit', display: 'block', marginBottom: 6 }}>
        {label}
      </label>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        style={{
          background: '#0c1018',
          border: '1px solid #1e293b',
          borderRadius: 8,
          padding: '8px 12px',
          color: '#94a3b8',
          fontFamily: 'Outfit',
          fontSize: 13,
          outline: 'none',
          width: '100%',
          cursor: 'pointer',
        }}
      >
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

export default function SettingsPanel() {
  const navigate = useNavigate();
  const [presets, setPresets] = useState([]);
  const [newPresetName, setNewPresetName] = useState('');
  const [adapterSummary, setAdapterSummary] = useState({ total_disk_mb: 0, count: 0 });
  const [cleanupBusy, setCleanupBusy] = useState(false);
  const [autoSchedule, setAutoSchedule] = useState({ enabled: false, intervalHours: 24 });

  const [cfg, setCfg] = useState({
    mutationRate: 5,
    temperature: 72,
    topK: 50,
    maxGenerations: 30,
    populationSize: 8,
    model: 'llama3.2:3b',
    evalFreq: 'every_gen',
    autoPromote: true,
    discardOnRegress: true,
    streamLogs: true,
    hfToken: 'hf_••••••••••••••••••••••••••',
    openaiKey: 'sk-••••••••••••••••••••••••••••••••',
  });

  function set(k, v) { setCfg(c => ({ ...c, [k]: v })); }
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(AUTOSCHEDULE_KEY);
      if (raw) setAutoSchedule(JSON.parse(raw));
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [p, a] = await Promise.all([
          fetchPresets(),
          fetchAdapters(),
        ]);
        if (!cancelled && p?.presets) setPresets(p.presets);
        if (!cancelled && a) {
          setAdapterSummary({
            total_disk_mb: a.total_disk_mb ?? 0,
            count: a.adapters?.length ?? 0,
          });
        }
      } catch {
        /* ignore */
      }
    })();
    return () => { cancelled = true; };
  }, []);

  function persistAutoSchedule(next) {
    setAutoSchedule(next);
    try {
      localStorage.setItem(AUTOSCHEDULE_KEY, JSON.stringify(next));
    } catch {
      /* ignore */
    }
  }

  function handleSave() {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  async function handleCreatePreset() {
    const name = newPresetName.trim();
    if (!name) return;
    try {
      await savePreset(name, {
        base_model: cfg.model,
        max_generations: cfg.maxGenerations,
        lora_rank: 16,
        lora_alpha: 32,
        learning_rate: 2e-4,
        batch_size: 2,
        max_samples: 3000,
      });
      setNewPresetName('');
      const p = await fetchPresets();
      if (p?.presets) setPresets(p.presets);
    } catch {
      /* ignore */
    }
  }

  async function handleDeletePreset(name, isBuiltin) {
    if (isBuiltin) return;
    try {
      await deletePreset(name);
      const p = await fetchPresets();
      if (p?.presets) setPresets(p.presets);
    } catch {
      /* ignore */
    }
  }

  async function handleCleanup() {
    setCleanupBusy(true);
    try {
      await cleanupAdapters({ older_than_days: 30, keep_promoted: 5 });
      const a = await fetchAdapters();
      if (a) {
        setAdapterSummary({
          total_disk_mb: a.total_disk_mb ?? 0,
          count: a.adapters?.length ?? 0,
        });
      }
    } catch {
      /* ignore */
    } finally {
      setCleanupBusy(false);
    }
  }

  return (
    <div>
      <Section title="EVOLUTION PRESETS">
        <p style={{ fontSize: 12, color: C.txtM, fontFamily: F.ui, marginBottom: 12 }}>
          {`Built-in presets are read-only. "Use" opens the dashboard with that preset selected.`}
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 16 }}>
          {presets.map((p) => (
            <div
              key={p.name}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 8,
                padding: '10px 12px',
                background: C.bgI,
                border: `1px solid ${C.border}`,
                borderRadius: 8,
              }}
            >
              <div style={{ fontFamily: F.mono, fontSize: 13, color: C.txtS }}>
                {p.name}
                {p.is_builtin ? (
                  <span style={{ marginLeft: 8, fontSize: 11, color: C.txtM }}>(built-in)</span>
                ) : null}
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <button
                  type="button"
                  onClick={() => navigate(`/dashboard?preset=${encodeURIComponent(p.name)}`)}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 4,
                    padding: '4px 10px',
                    fontSize: 11,
                    fontFamily: F.ui,
                    background: C.accDim,
                    border: `1px solid ${C.borderA}`,
                    borderRadius: 6,
                    color: C.acc,
                    cursor: 'pointer',
                  }}
                >
                  <Sparkles size={12} /> Use
                </button>
                {!p.is_builtin ? (
                  <button
                    type="button"
                    onClick={() => handleDeletePreset(p.name, p.is_builtin)}
                    style={{
                      padding: '4px 8px',
                      background: 'transparent',
                      border: `1px solid ${C.border}`,
                      borderRadius: 6,
                      color: C.danger,
                      cursor: 'pointer',
                    }}
                    aria-label={`Delete ${p.name}`}
                  >
                    <Trash2 size={14} />
                  </button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div style={{ flex: '1 1 180px' }}>
            <label style={{ fontSize: 11, color: C.txtM, fontFamily: F.ui }}>New preset name</label>
            <input
              value={newPresetName}
              onChange={(e) => setNewPresetName(e.target.value)}
              placeholder="my-preset"
              style={{
                marginTop: 4,
                width: '100%',
                padding: '8px 10px',
                background: C.bgS,
                border: `1px solid ${C.border}`,
                borderRadius: 8,
                color: C.txtP,
                fontFamily: F.mono,
                fontSize: 13,
              }}
            />
          </div>
          <button
            type="button"
            onClick={handleCreatePreset}
            style={{
              padding: '8px 14px',
              background: C.indDim,
              border: `1px solid ${C.borderI}`,
              borderRadius: 8,
              color: C.ind,
              fontFamily: F.ui,
              fontSize: 12,
              cursor: 'pointer',
            }}
          >
            Save current sliders as preset
          </button>
        </div>
      </Section>

      <Section title="ADAPTER STORAGE">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
          <HardDrive size={18} color={C.acc} aria-hidden />
          <div style={{ fontFamily: F.mono, fontSize: 13, color: C.txtS }}>
            {adapterSummary.count} adapters · {(adapterSummary.total_disk_mb ?? 0).toFixed(1)} MB total
          </div>
        </div>
        <button
          type="button"
          disabled={cleanupBusy}
          onClick={handleCleanup}
          style={{
            padding: '8px 16px',
            background: cleanupBusy ? C.bgE : C.warningDim,
            border: `1px solid ${C.border}`,
            borderRadius: 8,
            color: C.warning,
            fontFamily: F.ui,
            fontSize: 13,
            cursor: cleanupBusy ? 'not-allowed' : 'pointer',
          }}
        >
          {cleanupBusy ? 'Cleaning…' : 'Cleanup (30d, keep 5 promoted)'}
        </button>
      </Section>

      <Section title="AUTO-EVOLUTION SCHEDULE">
        <p style={{ fontSize: 12, color: C.txtM, fontFamily: F.ui, marginBottom: 12 }}>
          <Clock size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
          Toggle is stored locally. Configure the matching cron in n8n (
          <code style={{ color: C.txtS }}>evolution-scheduler.json</code>
          ) separately.
        </p>
        <Toggle
          label="Enable auto-evolution window"
          value={autoSchedule.enabled}
          onChange={(v) => persistAutoSchedule({ ...autoSchedule, enabled: v })}
          description="When on, your scheduled n8n workflow can start runs without manual action."
        />
        <div style={{ marginTop: 12 }}>
          <label style={{ fontSize: 12, color: C.txtM, fontFamily: F.ui }}>Interval (hours)</label>
          <input
            type="number"
            min={1}
            value={autoSchedule.intervalHours}
            onChange={(e) =>
              persistAutoSchedule({
                ...autoSchedule,
                intervalHours: Math.max(1, parseInt(e.target.value, 10) || 1),
              })
            }
            style={{
              marginTop: 4,
              width: 120,
              padding: '8px 10px',
              background: '#0c1018',
              border: '1px solid #1e293b',
              borderRadius: 8,
              color: '#94a3b8',
              fontFamily: 'JetBrains Mono',
              fontSize: 13,
            }}
          />
        </div>
      </Section>

      <Section title="EVOLUTION PARAMETERS">
        <Slider label="Mutation Rate" value={cfg.mutationRate} onChange={v => set('mutationRate', v)} min={1} max={20} step={1} unit="%" />
        <Slider label="Temperature" value={cfg.temperature} onChange={v => set('temperature', v)} min={1} max={200} step={1} unit="" />
        <Slider label="Top-K Sampling" value={cfg.topK} onChange={v => set('topK', v)} min={1} max={200} step={1} />
        <Slider label="Max Generations" value={cfg.maxGenerations} onChange={v => set('maxGenerations', v)} min={5} max={100} step={5} />
        <Slider label="Population Size" value={cfg.populationSize} onChange={v => set('populationSize', v)} min={2} max={32} step={2} />
      </Section>

      <Section title="MODEL CONFIGURATION">
        <Select
          label="Base Model"
          value={cfg.model}
          onChange={v => set('model', v)}
          options={[
            { value: 'llama3.2:3b', label: 'LLaMA 3.2 3B' },
            { value: 'llama3.2:8b', label: 'LLaMA 3.2 8B' },
            { value: 'mistral:7b', label: 'Mistral 7B' },
            { value: 'phi3:mini', label: 'Phi-3 Mini' },
            { value: 'gemma2:2b', label: 'Gemma 2 2B' },
          ]}
        />
        <Select
          label="Evaluation Frequency"
          value={cfg.evalFreq}
          onChange={v => set('evalFreq', v)}
          options={[
            { value: 'every_gen', label: 'Every Generation' },
            { value: 'every_5', label: 'Every 5 Generations' },
            { value: 'on_improve', label: 'On Improvement Only' },
          ]}
        />
      </Section>

      <Section title="BEHAVIOR">
        <Toggle label="Auto-promote winners" value={cfg.autoPromote} onChange={v => set('autoPromote', v)}
          description="Automatically promote child if it beats parent on all benchmarks" />
        <Toggle label="Discard on regression" value={cfg.discardOnRegress} onChange={v => set('discardOnRegress', v)}
          description="Immediately discard generations that regress on any primary benchmark" />
        <Toggle label="Stream logs" value={cfg.streamLogs} onChange={v => set('streamLogs', v)}
          description="Stream training logs in real time to the activity feed" />
      </Section>

      <Section title="API KEYS">
        <ApiKey label="Hugging Face Token" value={cfg.hfToken} onChange={v => set('hfToken', v)} />
        <ApiKey label="OpenAI API Key (eval baseline)" value={cfg.openaiKey} onChange={v => set('openaiKey', v)} />
      </Section>

      <Section title="SYSTEM INFO">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {[
            ['Platform', navigator.platform || 'Unknown'],
            ['Browser', navigator.userAgent.split(' ').slice(-1)[0]],
            ['API Endpoint', 'http://localhost:8000'],
            ['Frontend Version', 'v0.1.0'],
            ['Build', 'Vite 5.4 / React 18.3'],
          ].map(([k, v]) => (
            <div key={k} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 12, color: '#64748b', fontFamily: 'Outfit' }}>{k}</span>
              <span style={{ fontSize: 12, fontFamily: 'JetBrains Mono', color: '#94a3b8' }}>{v}</span>
            </div>
          ))}
        </div>
      </Section>

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <MagneticButton
          onClick={handleSave}
          style={{
            padding: '10px 24px',
            background: saved ? '#1a3d0a' : 'linear-gradient(135deg, #76b900, #a3e635)',
            border: 'none',
            borderRadius: 8,
            color: '#fff',
            cursor: 'pointer',
            fontFamily: 'Outfit',
            fontWeight: 600,
            fontSize: 14,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            transition: 'background 300ms',
          }}
        >
          <Save size={14} />
          {saved ? 'Saved!' : 'Save Settings'}
        </MagneticButton>
      </div>
    </div>
  );
}
