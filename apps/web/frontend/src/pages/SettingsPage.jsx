import { useState } from 'react';
import { C, F } from '../config/colors';

function Section({ title, children }) {
  return (
    <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 20, marginBottom: 16 }}>
      <div style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.txtM, marginBottom: 16, paddingBottom: 12, borderBottom: `1px solid ${C.border}` }}>
        {title}
      </div>
      {children}
    </div>
  );
}

function Field({ label, value, onChange, type = 'text', placeholder }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{ display: 'block', fontFamily: F.ui, fontSize: 11, fontWeight: 600, color: C.txtM, marginBottom: 6, letterSpacing: '0.04em', textTransform: 'uppercase' }}>{label}</label>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        style={{ width: '100%', background: C.bgI, border: `1px solid ${C.border}`, borderRadius: 4, padding: '8px 12px', fontFamily: F.mono, fontSize: 13, color: C.txtP, outline: 'none', transition: 'border-color 150ms' }}
        onFocus={e => e.target.style.borderColor = C.ind}
        onBlur={e => e.target.style.borderColor = C.border}
      />
    </div>
  );
}

function Slider({ label, value, onChange, min = 0, max = 100, step = 1 }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <label style={{ fontFamily: F.ui, fontSize: 11, fontWeight: 600, color: C.txtM, letterSpacing: '0.04em', textTransform: 'uppercase' }}>{label}</label>
        <span style={{ fontFamily: F.mono, fontSize: 12, color: C.txtP }}>{value}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={e => onChange(Number(e.target.value))}
        style={{ width: '100%', accentColor: C.acc }} />
    </div>
  );
}

export default function SettingsPage() {
  const base = import.meta.env.VITE_API_BASE_URL || '';
  const [ollama, setOllama] = useState(import.meta.env.VITE_OLLAMA_HOST || 'http://localhost:11434');
  const [vllm, setVllm]     = useState(import.meta.env.VITE_VLLM_HOST || 'http://localhost:8001');
  const [n8n, setN8n]       = useState(import.meta.env.VITE_N8N_HOST || 'http://localhost:5678');
  const [model, setModel]   = useState('llama3.2:3b');
  const [maxGen, setMaxGen] = useState(10);
  const [rank, setRank]     = useState(16);
  const [alpha, setAlpha]   = useState(32);
  const [lr, setLr]         = useState(0.0002);
  const [batch, setBatch]   = useState(2);
  const [saved, setSaved]   = useState(false);

  const save = () => { setSaved(true); setTimeout(() => setSaved(false), 2000); };

  return (
    <div style={{ maxWidth: 760, margin: '0 auto' }}>
      <Section title="API Configuration">
        <Field label="API Base URL" value={base} onChange={() => {}} placeholder="empty = same-origin /api (Docker nginx or Vite proxy)" />
        <Field label="Ollama Host" value={ollama} onChange={setOllama} placeholder="http://localhost:11434" />
        <Field label="vLLM Host (DGX)" value={vllm} onChange={setVllm} placeholder="http://localhost:8001" />
        <Field label="n8n Host" value={n8n} onChange={setN8n} placeholder="http://localhost:5678" />
        <div style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM, marginTop: -6 }}>
          Override via VITE_* environment variables in frontend/.env
        </div>
      </Section>

      <Section title="Model Defaults">
        <Field label="Base Model" value={model} onChange={setModel} placeholder="llama3.2:3b" />
      </Section>

      <Section title="Evolution Parameters">
        <Slider label="Max Generations" value={maxGen} onChange={setMaxGen} min={1} max={50} />
        <Slider label="LoRA Rank" value={rank} onChange={setRank} min={4} max={64} step={4} />
        <Slider label="LoRA Alpha" value={alpha} onChange={setAlpha} min={8} max={128} step={8} />
        <Slider label="Batch Size" value={batch} onChange={setBatch} min={1} max={16} />
        <div style={{ marginBottom: 14 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
            <label style={{ fontFamily: F.ui, fontSize: 11, fontWeight: 600, color: C.txtM, letterSpacing: '0.04em', textTransform: 'uppercase' }}>Learning Rate</label>
            <span style={{ fontFamily: F.mono, fontSize: 12, color: C.txtP }}>{lr}</span>
          </div>
          <input type="number" value={lr} onChange={e => setLr(e.target.value)} step="0.0001" min="0.00001" max="0.01"
            style={{ width: '100%', background: C.bgI, border: `1px solid ${C.border}`, borderRadius: 4, padding: '8px 12px', fontFamily: F.mono, fontSize: 13, color: C.txtP, outline: 'none' }} />
        </div>
      </Section>

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <button onClick={save} style={{ padding: '10px 24px', background: saved ? C.success : C.acc, color: '#000', border: 'none', borderRadius: 6, cursor: 'pointer', fontFamily: F.ui, fontSize: 14, fontWeight: 700, transition: 'background 300ms', boxShadow: `0 0 20px ${C.accGlow}` }}>
          {saved ? 'Saved ✓' : 'Save Settings'}
        </button>
      </div>
    </div>
  );
}
