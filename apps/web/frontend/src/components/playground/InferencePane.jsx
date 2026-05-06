import { useState, useEffect, useRef } from 'react';

const INFERENCE_STORAGE_KEY = 'mf.playground.inference.v1';
import { RotateCcw, Zap, Trophy, Save } from 'lucide-react';
import { apiFetch, fetchAdapters, fetchDatasets, getApiKey, savePairToDataset, serveAdapter, setApiKey } from '../../config/api';
import { C, F } from '../../config/colors';
import DNALoader from '../shared/DNALoader';
import MagneticButton from '../shared/MagneticButton';

/** Ollama `model` param must be a local tag, not a HuggingFace repo id. */
function ollamaBaseTagFromRegistryBase(base) {
  const s = (base && String(base).trim()) || '';
  if (!s) return 'llama3.2:3b';
  // Typical HF ids: org/model — Ollama expects e.g. llama3.2:3b
  if (s.includes('/') && !s.includes(':')) return 'llama3.2:3b';
  return s;
}

const EXAMPLE_PROMPTS = [
  'Explain quantum entanglement in simple terms.',
  'Write a Python function to compute Fibonacci using memoization.',
  'What is the difference between supervised and unsupervised learning?',
  'Solve: If 3x + 7 = 22, what is x?',
];

function TypewriterText({ text, speed = 20 }) {
  const [displayed, setDisplayed] = useState('');

  useEffect(() => {
    setDisplayed('');
    let i = 0;
    const iv = setInterval(() => {
      i++;
      setDisplayed(text.slice(0, i));
      if (i >= text.length) clearInterval(iv);
    }, speed);
    return () => clearInterval(iv);
  }, [text, speed]);

  return (
    <span>
      {displayed}
      {displayed.length < text.length && (
        <span className="animate-cursor" style={{ borderRight: '1px solid #76b900', marginLeft: 1 }} />
      )}
    </span>
  );
}

export default function InferencePane() {
  const [prompt, setPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const [responses, setResponses] = useState({ base: '', champion: '' });
  const [meta, setMeta] = useState({ base: null, champion: null });
  const [submitted, setSubmitted] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const [adapters, setAdapters] = useState([]);
  const [datasets, setDatasets] = useState([]);
  const [adapterId, setAdapterId] = useState('');
  const [saveDs, setSaveDs] = useState('');
  const [badge, setBadge] = useState('');
  /** Ollama tag for the promoted champion (from `/api/models/champion`). */
  const [championBase, setChampionBase] = useState('');
  /** Last error from a failed Run Inference, surfaced verbatim with a self-heal button. */
  const [submitError, setSubmitError] = useState(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(INFERENCE_STORAGE_KEY);
      if (raw) {
        const saved = JSON.parse(raw);
        if (typeof saved.prompt === 'string') setPrompt(saved.prompt);
        if (saved.responses && typeof saved.responses === 'object') {
          setResponses({
            base: String(saved.responses.base ?? ''),
            champion: String(saved.responses.champion ?? ''),
          });
        }
        if (saved.meta && typeof saved.meta === 'object') setMeta(saved.meta);
        if (typeof saved.submitted === 'boolean') setSubmitted(saved.submitted);
        if (typeof saved.adapterId === 'string') setAdapterId(saved.adapterId);
      }
    } catch {
      /* ignore */
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    try {
      sessionStorage.setItem(
        INFERENCE_STORAGE_KEY,
        JSON.stringify({ prompt, responses, meta, submitted, adapterId })
      );
    } catch {
      /* ignore */
    }
  }, [hydrated, prompt, responses, meta, submitted, adapterId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const a = await fetchAdapters().catch(() => null);
        if (cancelled || !a) return;
        const list = a.adapters || [];
        setAdapters(list);
        const cid = a.champion_id || list.find((x) => x.is_champion)?.adapter_id;
        if (cid) {
          setAdapterId(cid);
          setBadge(cid);
        }
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const d = await fetchDatasets().catch(() => null);
        if (cancelled || !d) return;
        const customs = (d.datasets || []).filter((x) => x.kind === 'custom');
        setDatasets(customs);
        setSaveDs((prev) => prev || (customs[0]?.dataset_id ?? ''));
      } catch {
        setDatasets([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    apiFetch('/api/models/champion')
      .then((c) => {
        if (cancelled || !c) return;
        const bm = c.base_model || c.name;
        if (bm) setChampionBase(String(bm));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSubmit() {
    if (!prompt.trim() || loading) return;
    setLoading(true);
    setSubmitted(false);
    setSubmitError(null);
    setResponses({ base: '', champion: '' });
    setMeta({ base: null, champion: null });
    try {
      let modelBTag = 'llama3.2:3b';
      let targetId = adapterId;
      if (!targetId) {
        targetId = adapters.find((x) => x.is_champion)?.adapter_id;
      }
      if (!targetId) {
        const fresh = await fetchAdapters().catch(() => null);
        targetId = fresh?.champion_id;
      }

      const baseModel = ollamaBaseTagFromRegistryBase(championBase);

      if (targetId) {
        const served = await serveAdapter(targetId);
        const sel = adapters.find((x) => x.adapter_id === targetId);
        // Ollama can only serve local tags. If the adapter has not been served as
        // an Ollama model, fall back to the resolved base tag so the champion pane
        // doesn't trip into the mock branch with an HF repo id like
        // `meta-llama/Llama-3.2-3B-Instruct`.
        modelBTag = served?.ollama_model
          || ollamaBaseTagFromRegistryBase(sel?.base_model)
          || baseModel;
        setBadge(targetId);
      }

      const result = await apiFetch('/api/infer/compare', {
        method: 'POST',
        body: JSON.stringify({
          prompt,
          model_a: baseModel,
          model_b: modelBTag || baseModel,
          max_tokens: 256,
          temperature: 0.7,
        }),
      });

      if (result?.base && result?.champion) {
        setResponses({
          base: result.base.response ?? '',
          champion: result.champion.response ?? '',
        });
        setMeta({
          base: result.base,
          champion: result.champion,
        });
      } else {
        setResponses({
          base: 'No response returned from the API.',
          champion: 'No response returned from the API.',
        });
      }
      setSubmitted(true);
    } catch (err) {
      // Surface the *real* failure (status code + body) so the user can act on it.
      // The previous generic "Request failed. Check API key…" hid 401s caused by
      // a stale custom key in localStorage that overrode the working build-time key.
      const status = err?.status;
      const detail = err?.body?.detail || err?.message || 'Unknown error';
      const detailStr = typeof detail === 'string' ? detail : JSON.stringify(detail);
      const reason =
        status === 401 || status === 403
          ? `Auth failed (HTTP ${status}). Your saved API key looks wrong — clear it below to use the build-in key.`
          : status
            ? `HTTP ${status}: ${detailStr}`
            : detailStr;
      setResponses({
        base: `Request failed. ${reason}`,
        champion: `Request failed. ${reason}`,
      });
      setSubmitError({ status, reason, isAuth: status === 401 || status === 403 });
      setSubmitted(true);
    } finally {
      setLoading(false);
    }
  }

  function clearStoredApiKey() {
    setApiKey('');
    setSubmitError(null);
    // Force a fresh attempt with the (build-time) default key.
    setTimeout(() => handleSubmit(), 0);
  }

  async function handleSavePair(which) {
    if (!saveDs || !prompt.trim()) return;
    const text = which === 'base' ? responses.base : responses.champion;
    try {
      await savePairToDataset(saveDs, prompt, text);
    } catch {
      /* ignore */
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit();
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 16 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 8,
          padding: '8px 12px',
          background: C.bgC,
          border: `1px solid ${C.border}`,
          borderRadius: 8,
        }}
      >
        <div style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM, lineHeight: 1.5 }}>
          <div>
            Base model: <span style={{ color: C.acc }}>{championBase || '—'}</span>
          </div>
          <div style={{ marginTop: 2 }}>
            Adapter: <span style={{ color: C.acc }}>{badge || 'champion (default)'}</span>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <label style={{ fontSize: 11, color: C.txtM, fontFamily: F.ui }}>Adapter</label>
          <select
            value={adapterId}
            onChange={(e) => setAdapterId(e.target.value)}
            style={{
              background: C.bgI,
              border: `1px solid ${C.border}`,
              borderRadius: 6,
              color: C.txtP,
              fontSize: 12,
              fontFamily: F.mono,
              padding: '6px 10px',
            }}
          >
            <option value="">Champion (default)</option>
            {adapters.map((a) => (
              <option key={a.adapter_id} value={a.adapter_id}>
                {a.adapter_id} ({a.status})
              </option>
            ))}
          </select>
        </div>
      </div>

      <div
        style={{
          background: '#111827',
          border: '1px solid #1e293b',
          borderRadius: 12,
          padding: 16,
        }}
      >
        <div
          style={{
            fontSize: 11,
            color: '#64748b',
            fontFamily: 'JetBrains Mono',
            letterSpacing: 2,
            marginBottom: 10,
          }}
        >
          PROMPT
        </div>
        <textarea
          ref={textareaRef}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Enter a prompt... (⌘+Enter to run)"
          rows={4}
          style={{
            width: '100%',
            background: '#0c1018',
            border: '1px solid #1e293b',
            borderRadius: 8,
            padding: '10px 14px',
            color: '#f1f5f9',
            fontFamily: 'JetBrains Mono',
            fontSize: 13,
            resize: 'vertical',
            outline: 'none',
            transition: 'border-color 200ms',
          }}
          onFocus={(e) => (e.target.style.borderColor = '#818cf8')}
          onBlur={(e) => (e.target.style.borderColor = '#1e293b')}
        />
        <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', gap: 6, flex: 1, flexWrap: 'wrap' }}>
            {EXAMPLE_PROMPTS.map((p, i) => (
              <button
                key={i}
                type="button"
                onClick={() => {
                  setPrompt(p);
                  textareaRef.current?.focus();
                }}
                style={{
                  padding: '4px 10px',
                  background: 'transparent',
                  border: '1px solid #1e293b',
                  borderRadius: 6,
                  color: '#64748b',
                  fontSize: 11,
                  fontFamily: 'Outfit',
                  cursor: 'pointer',
                  transition: 'all 200ms',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = '#334155';
                  e.currentTarget.style.color = '#94a3b8';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = '#1e293b';
                  e.currentTarget.style.color = '#64748b';
                }}
              >
                {p.slice(0, 30)}…
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button"
              onClick={() => {
                setPrompt('');
                setSubmitted(false);
                setResponses({ base: '', champion: '' });
              }}
              style={{
                padding: '8px 12px',
                background: 'transparent',
                border: '1px solid #1e293b',
                borderRadius: 8,
                color: '#64748b',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                fontSize: 13,
              }}
            >
              <RotateCcw size={13} /> Reset
            </button>
            <MagneticButton
              onClick={handleSubmit}
              className="flex items-center gap-2"
              style={{
                padding: '8px 20px',
                background: loading ? '#1a2235' : 'linear-gradient(135deg, #818cf8, #76b900)',
                border: 'none',
                borderRadius: 8,
                color: '#fff',
                cursor: loading ? 'not-allowed' : 'pointer',
                fontSize: 13,
                fontFamily: 'Outfit',
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}
            >
              {loading ? (
                <>
                  <DNALoader size={14} /> Running…
                </>
              ) : (
                <>
                  <Zap size={13} /> Run Inference
                </>
              )}
            </MagneticButton>
          </div>
        </div>
      </div>

      {submitError && !loading ? (
        <div
          role="alert"
          style={{
            display: 'flex',
            gap: 12,
            alignItems: 'flex-start',
            padding: '10px 14px',
            background: 'rgba(239,68,68,0.08)',
            border: `1px solid rgba(239,68,68,0.35)`,
            borderRadius: 8,
            color: C.danger,
            fontFamily: F.ui,
            fontSize: 12,
            lineHeight: 1.5,
          }}
        >
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, marginBottom: 2 }}>Inference failed</div>
            <div style={{ color: C.txtS }}>{submitError.reason}</div>
            {submitError.isAuth ? (
              <div style={{ color: C.txtM, marginTop: 6, fontFamily: F.mono, fontSize: 11 }}>
                Stored key (localStorage <code>modelforge_api_key</code>):{' '}
                <code>
                  {(() => {
                    const k = (typeof window !== 'undefined'
                      && window.localStorage.getItem('modelforge_api_key')) || '';
                    return k ? `${k.slice(0, 6)}…${k.slice(-4)}` : '(none)';
                  })()}
                </code>
              </div>
            ) : null}
          </div>
          {submitError.isAuth ? (
            <button
              type="button"
              onClick={clearStoredApiKey}
              style={{
                padding: '6px 10px',
                background: C.danger,
                color: '#fff',
                border: 'none',
                borderRadius: 6,
                cursor: 'pointer',
                fontFamily: F.ui,
                fontSize: 11,
                fontWeight: 600,
                whiteSpace: 'nowrap',
              }}
            >
              Clear stored key & retry
            </button>
          ) : null}
        </div>
      ) : null}

      {(submitted || loading) && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, flex: 1 }}>
          {[
            { key: 'base', label: 'BASE MODEL', color: '#818cf8', subtitle: 'model_a', crown: false },
            { key: 'champion', label: 'ADAPTER / CHAMPION', color: '#76b900', subtitle: 'model_b', crown: true },
          ].map(({ key, label, color, subtitle, crown }) => (
            <div
              key={key}
              style={{
                background: '#111827',
                border: `1px solid ${loading ? '#1e293b' : color + '33'}`,
                borderRadius: 12,
                padding: 16,
                transition: 'border-color 400ms',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
                <div>
                  <div
                    style={{ fontSize: 10, fontFamily: 'JetBrains Mono', color, letterSpacing: 1 }}
                  >
                    {label}
                  </div>
                  <div style={{ fontSize: 12, color: '#64748b', fontFamily: 'Outfit', marginTop: 2 }}>
                    {subtitle}
                  </div>
                </div>
                {crown && (
                  <Trophy size={18} color={color} style={{ animation: 'crown-float 3s ease-in-out infinite' }} aria-hidden />
                )}
              </div>
              <div
                style={{
                  minHeight: 120,
                  fontSize: 13,
                  lineHeight: 1.7,
                  color: '#94a3b8',
                  fontFamily: 'Outfit',
                }}
              >
                {loading ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '20px 0' }}>
                    <DNALoader size={24} />
                    <span style={{ color: '#475569', fontSize: 12, fontFamily: 'JetBrains Mono' }}>
                      Generating…
                    </span>
                  </div>
                ) : responses[key] ? (
                  <TypewriterText text={responses[key]} speed={key === 'champion' ? 18 : 22} />
                ) : null}
              </div>
              {!loading && meta[key]?.latency_ms != null && (
                <div
                  style={{
                    marginTop: 12,
                    fontSize: 11,
                    fontFamily: 'JetBrains Mono',
                    color: '#475569',
                  }}
                >
                  {meta[key]?.latency_ms != null && (
                    <span style={{ marginRight: 12 }}>{Math.round(meta[key].latency_ms)} ms</span>
                  )}
                  {meta[key]?.tokens != null && <span>{meta[key].tokens} tokens</span>}
                </div>
              )}
              {!loading && responses[key] && datasets.length > 0 && (
                <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <select
                    value={saveDs}
                    onChange={(e) => setSaveDs(e.target.value)}
                    style={{
                      fontSize: 11,
                      background: C.bgI,
                      border: `1px solid ${C.border}`,
                      borderRadius: 4,
                      color: C.txtS,
                      padding: '4px 8px',
                    }}
                  >
                    {datasets.map((d) => (
                      <option key={d.dataset_id} value={d.dataset_id}>
                        {d.dataset_id.slice(0, 8)}…
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => handleSavePair(key)}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 4,
                      fontSize: 11,
                      padding: '4px 10px',
                      background: C.accDim,
                      border: `1px solid ${C.border}`,
                      borderRadius: 6,
                      color: C.acc,
                      cursor: 'pointer',
                    }}
                  >
                    <Save size={12} /> Save pair
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
