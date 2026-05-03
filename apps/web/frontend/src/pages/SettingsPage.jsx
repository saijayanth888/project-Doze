import { useCallback, useEffect, useState } from 'react';
import { Eye, EyeOff, RotateCcw } from 'lucide-react';
import { C, F } from '../config/colors';
import { apiFetch, getApiBase, setApiKey } from '../config/api';
import Button from '../components/shared/Button';
import { useToast } from '../context/ToastContext';

const STORAGE_KEY = 'mf_settings';

function loadStored() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    /* ignore */
  }
  return null;
}

function Section({ title, children }) {
  return (
    <div className="mf-card-hover" style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 20, marginBottom: 16 }}>
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
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        style={{ width: '100%', background: C.bgI, border: `1px solid ${C.border}`, borderRadius: 4, padding: '8px 12px', fontFamily: F.mono, fontSize: 13, color: C.txtP, outline: 'none', transition: 'border-color 150ms' }}
        onFocus={(e) => {
          e.target.style.borderColor = C.ind;
        }}
        onBlur={(e) => {
          e.target.style.borderColor = C.border;
        }}
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
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} style={{ width: '100%', accentColor: C.acc }} />
    </div>
  );
}

export default function SettingsPage() {
  const { show } = useToast();
  const stored = typeof window !== 'undefined' ? loadStored() : null;

  const [apiBase, setApiBase] = useState(() => stored?.apiBase ?? '');
  const [ollama, setOllama] = useState(() => stored?.ollama ?? import.meta.env.VITE_OLLAMA_HOST ?? 'http://localhost:11434');
  const [vllm, setVllm] = useState(() => stored?.vllm ?? import.meta.env.VITE_VLLM_HOST ?? 'http://localhost:8001');
  const [n8n, setN8n] = useState(() => stored?.n8n ?? import.meta.env.VITE_N8N_HOST ?? 'http://localhost:5679');
  const [model, setModel] = useState(() => stored?.model ?? 'llama3.2:3b');
  const [maxGen, setMaxGen] = useState(() => stored?.maxGen ?? 10);
  const [rank, setRank] = useState(() => stored?.rank ?? 16);
  const [alpha, setAlpha] = useState(() => stored?.alpha ?? 32);
  const [lr, setLr] = useState(() => stored?.lr ?? 0.0002);
  const [batch, setBatch] = useState(() => stored?.batch ?? 2);
  const [apiKey, setApiKeyState] = useState(() => {
    try {
      return window.localStorage.getItem('modelforge_api_key') || '';
    } catch {
      return '';
    }
  });
  const [showKey, setShowKey] = useState(false);
  const [saved, setSaved] = useState(false);
  const [connOk, setConnOk] = useState(null);

  useEffect(() => {
    if (!apiBase.trim()) {
      try {
        window.localStorage.removeItem('modelforge_api_base');
      } catch {
        /* ignore */
      }
    } else {
      try {
        window.localStorage.setItem('modelforge_api_base', apiBase.trim());
      } catch {
        /* ignore */
      }
    }
  }, [apiBase]);

  const save = useCallback(() => {
    const payload = { apiBase, ollama, vllm, n8n, model, maxGen, rank, alpha, lr, batch };
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
      setApiKey(apiKey.trim());
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2000);
      show('Settings saved.', 'success');
    } catch (e) {
      show(`Could not save: ${e?.message || e}`, 'danger');
    }
  }, [apiBase, ollama, vllm, n8n, model, maxGen, rank, alpha, lr, batch, apiKey, show]);

  const resetDefaults = useCallback(() => {
    try {
      window.localStorage.removeItem(STORAGE_KEY);
      window.localStorage.removeItem('modelforge_api_base');
    } catch {
      /* ignore */
    }
    setApiBase('');
    setOllama(import.meta.env.VITE_OLLAMA_HOST || 'http://localhost:11434');
    setVllm(import.meta.env.VITE_VLLM_HOST || 'http://localhost:8001');
    setN8n(import.meta.env.VITE_N8N_HOST || 'http://localhost:5679');
    setModel('llama3.2:3b');
    setMaxGen(10);
    setRank(16);
    setAlpha(32);
    setLr(0.0002);
    setBatch(2);
    show('Reset to defaults (API key unchanged).', 'info');
  }, [show]);

  const testConnection = useCallback(async () => {
    setConnOk(null);
    try {
      await apiFetch('/api/system/status', {}, { timeoutMs: 8000 });
      setConnOk(true);
      show('API reachable.', 'success');
    } catch (e) {
      setConnOk(false);
      show(`Connection failed: ${e?.message || e}`, 'danger');
    }
  }, [show]);

  return (
    <div style={{ maxWidth: 760, margin: '0 auto' }}>
      <Section title="API Configuration">
        <Field
          label="API Base URL"
          value={apiBase}
          onChange={setApiBase}
          placeholder="empty = same-origin /api (Docker nginx or Vite proxy)"
        />
        <div style={{ marginBottom: 14 }}>
          <label style={{ display: 'block', fontFamily: F.ui, fontSize: 11, fontWeight: 600, color: C.txtM, marginBottom: 6, letterSpacing: '0.04em', textTransform: 'uppercase' }}>API Key</label>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input
              type={showKey ? 'text' : 'password'}
              value={apiKey}
              onChange={(e) => setApiKeyState(e.target.value)}
              placeholder="X-API-Key (stored in localStorage)"
              style={{ flex: 1, background: C.bgI, border: `1px solid ${C.border}`, borderRadius: 4, padding: '8px 12px', fontFamily: F.mono, fontSize: 13, color: C.txtP, outline: 'none' }}
            />
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => setShowKey((s) => !s)}
              aria-label={showKey ? 'Hide API key' : 'Show API key'}
            >
              {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
          <div style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM, marginTop: 6 }}>
            Current API origin: <strong style={{ color: C.txtS }}>{getApiBase() || '(same-origin)'}</strong>
            {apiKey.trim() ? ' · Key set' : ' · Key not set'}
          </div>
        </div>
        <Field label="Ollama Host" value={ollama} onChange={setOllama} placeholder="http://localhost:11434" />
        <Field label="vLLM Host (DGX)" value={vllm} onChange={setVllm} placeholder="http://localhost:8001" />
        <Field label="n8n Host" value={n8n} onChange={setN8n} placeholder="http://localhost:5679" />
        <div style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM, marginTop: -6 }}>Override via VITE_* in frontend/.env or save here (localStorage).</div>
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
          <input
            type="number"
            value={lr}
            onChange={(e) => setLr(Number(e.target.value))}
            step="0.0001"
            min="0.00001"
            max="0.01"
            style={{ width: '100%', background: C.bgI, border: `1px solid ${C.border}`, borderRadius: 4, padding: '8px 12px', fontFamily: F.mono, fontSize: 13, color: C.txtP, outline: 'none' }}
          />
        </div>
      </Section>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, justifyContent: 'flex-end' }}>
        <Button variant="ghost" onClick={resetDefaults}>
          <RotateCcw size={14} aria-hidden /> Reset
        </Button>
        <Button variant="secondary" onClick={testConnection}>
          Test connection
        </Button>
        <Button variant="primary" onClick={save}>
          {saved ? 'Saved' : 'Save settings'}
        </Button>
      </div>
      {connOk === true ? <p style={{ textAlign: 'right', fontSize: 12, color: C.success, marginTop: 8 }}>Last test: OK</p> : null}
      {connOk === false ? <p style={{ textAlign: 'right', fontSize: 12, color: C.danger, marginTop: 8 }}>Last test: failed</p> : null}
    </div>
  );
}
