import { useState } from 'react';
import { Eye, EyeOff, Save } from 'lucide-react';
import MagneticButton from '../shared/MagneticButton';

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

  function handleSave() {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <div>
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
