import { useState, useEffect, useRef, useCallback } from 'react';
import { Search, Download, Check, AlertTriangle, X, Loader } from 'lucide-react';
import { apiFetch } from '../../config/api';
import { useToast } from '../../context/ToastContext';
import InfoTooltip from './InfoTooltip';
import { CONCEPT_INFO } from '../../data/benchmarkInfo';

const RECENT_KEY = 'mf:recent-models';
const DEBOUNCE_MS = 600;

const SIZE_PRESETS = [
  { label: 'Small (1B)', id: 'TinyLlama/TinyLlama-1.1B-Chat-v1.0' },
  { label: 'Medium (3B)', id: 'meta-llama/Llama-3.2-3B-Instruct' },
  { label: 'Large (7-8B)', id: 'meta-llama/Meta-Llama-3.1-8B-Instruct' },
];

function loadRecent() {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveRecent(modelId) {
  try {
    const prev = loadRecent().filter((id) => id !== modelId);
    const next = [modelId, ...prev].slice(0, 5);
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
}

export default function ModelPicker({
  value = '',
  onChange,
  showMemoryEstimate = true,
  showPullButton = true,
  showPresets = true,
  disabled = false,
}) {
  const { show } = useToast();

  // Local models fetched from Ollama via the API
  const [localModels, setLocalModels] = useState([]);
  const [loadingLocal, setLoadingLocal] = useState(true);

  // Input state
  const [inputValue, setInputValue] = useState(value);
  const [showDropdown, setShowDropdown] = useState(false);

  // Validation state
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState(null); // null | { valid, model_id, ... }

  // Pull state
  const [pulling, setPulling] = useState(false);

  // Recent models
  const [recent, setRecent] = useState(loadRecent);

  const inputRef = useRef(null);
  const debounceRef = useRef(null);
  const dropdownRef = useRef(null);

  // Sync external value changes into local input
  useEffect(() => {
    setInputValue(value);
  }, [value]);

  // Fetch local Ollama models once
  useEffect(() => {
    let cancelled = false;
    setLoadingLocal(true);
    apiFetch('/api/models/')
      .then((data) => {
        if (!cancelled) {
          const ids = (data?.models || []).map((m) => m.id || m.base_model || m.name).filter(Boolean);
          setLocalModels(ids);
        }
      })
      .catch(() => {
        if (!cancelled) setLocalModels([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingLocal(false);
      });
    return () => { cancelled = true; };
  }, []);

  // Refresh local models list (called after successful pull)
  const refreshLocalModels = useCallback(() => {
    apiFetch('/api/models/')
      .then((data) => {
        const ids = (data?.models || []).map((m) => m.id || m.base_model || m.name).filter(Boolean);
        setLocalModels(ids);
      })
      .catch(() => {});
  }, []);

  // Debounced HF validation
  const triggerValidation = useCallback((modelId) => {
    if (!modelId.trim() || isLocalModel(modelId, localModels)) {
      setValidation(null);
      return;
    }
    setValidating(true);
    apiFetch('/api/models/validate', {
      method: 'POST',
      body: JSON.stringify({ model_id: modelId.trim() }),
    })
      .then((data) => setValidation(data))
      .catch(() => setValidation({ valid: false, model_id: modelId, reason: 'error' }))
      .finally(() => setValidating(false));
  }, [localModels]);

  // Handle input change — debounce validation
  function handleInputChange(e) {
    const val = e.target.value;
    setInputValue(val);
    setValidation(null);

    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (val.trim()) {
      debounceRef.current = setTimeout(() => triggerValidation(val), DEBOUNCE_MS);
    }
  }

  // Cleanup debounce on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  // Handle Enter key: immediate validation
  function handleKeyDown(e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (debounceRef.current) clearTimeout(debounceRef.current);
      const val = inputValue.trim();
      if (val) {
        const matchedLocal = localModels.find((id) => id.toLowerCase() === val.toLowerCase());
        if (matchedLocal) {
          selectModel(matchedLocal);
        } else {
          triggerValidation(val);
        }
      }
      setShowDropdown(false);
    } else if (e.key === 'Escape') {
      setShowDropdown(false);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setShowDropdown(true);
    }
  }

  function selectModel(modelId) {
    setInputValue(modelId);
    setShowDropdown(false);
    setValidation(null);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    saveRecent(modelId);
    setRecent(loadRecent());
    onChange?.(modelId);
  }

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(e) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target) &&
        inputRef.current &&
        !inputRef.current.contains(e.target)
      ) {
        setShowDropdown(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Pull model to Ollama
  async function handlePull() {
    if (!inputValue.trim()) return;
    setPulling(true);
    try {
      await apiFetch('/api/models/pull', {
        method: 'POST',
        body: JSON.stringify({ model: inputValue.trim() }),
      });
      show(`Model "${inputValue.trim()}" pulled successfully.`, 'success');
      refreshLocalModels();
    } catch (err) {
      show(`Pull failed: ${err?.message || 'unknown error'}`, 'danger');
    } finally {
      setPulling(false);
    }
  }

  // Filtered dropdown suggestions
  const query = inputValue.toLowerCase();
  const dropdownItems = localModels.filter(
    (id) => !query || id.toLowerCase().includes(query)
  );

  const isLocal = isLocalModel(inputValue, localModels);
  const showPull = showPullButton && !isLocal && validation?.valid === true;

  return (
    <div
      role="region"
      aria-label="model picker"
      style={{ display: 'flex', flexDirection: 'column', gap: 10, fontFamily: "var(--font-ui, 'Outfit', sans-serif)" }}
    >
      {/* Recent models */}
      {recent.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 6 }}>
          <span style={{ fontSize: 11, color: 'var(--text-secondary, #94a3b8)', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
            Recent
          </span>
          {recent.map((id) => (
            <button
              key={id}
              type="button"
              disabled={disabled}
              onClick={() => selectModel(id)}
              style={{
                padding: '2px 8px',
                borderRadius: 12,
                border: '1px solid var(--border, #1f2937)',
                background: 'var(--bg-card, #0f172a)',
                color: 'var(--text-secondary, #94a3b8)',
                fontSize: 11,
                cursor: disabled ? 'not-allowed' : 'pointer',
                fontFamily: "'JetBrains Mono', monospace",
                opacity: disabled ? 0.5 : 1,
                transition: 'border-color 0.15s, color 0.15s',
              }}
              onMouseEnter={(e) => {
                if (!disabled) {
                  e.target.style.borderColor = 'var(--accent-primary, #76b900)';
                  e.target.style.color = 'var(--text-primary, #f1f5f9)';
                }
              }}
              onMouseLeave={(e) => {
                e.target.style.borderColor = 'var(--border, #1f2937)';
                e.target.style.color = 'var(--text-secondary, #94a3b8)';
              }}
            >
              {id.length > 28 ? `…${id.slice(-26)}` : id}
            </button>
          ))}
        </div>
      )}

      {/* Combo input */}
      <div style={{ position: 'relative' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '8px 12px',
            background: 'var(--bg-card, #0f172a)',
            border: '1px solid var(--border, #1f2937)',
            borderRadius: 8,
            opacity: disabled ? 0.6 : 1,
            transition: 'border-color 0.15s, box-shadow 0.15s',
          }}
          onFocus={() => {}}
        >
          <Search size={14} style={{ color: 'var(--text-secondary, #94a3b8)', flexShrink: 0 }} />
          <input
            ref={inputRef}
            type="text"
            value={inputValue}
            disabled={disabled}
            placeholder="HuggingFace model id or pick from local…"
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            onFocus={() => setShowDropdown(true)}
            aria-label="model id"
            aria-autocomplete="list"
            aria-expanded={showDropdown}
            style={{
              flex: 1,
              background: 'transparent',
              border: 'none',
              outline: 'none',
              color: 'var(--text-primary, #f1f5f9)',
              fontSize: 13,
              fontFamily: "'JetBrains Mono', monospace",
              minWidth: 0,
            }}
          />
          {validating && (
            <Loader size={14} style={{ color: 'var(--text-secondary, #94a3b8)', animation: 'mf-spin 1s linear infinite', flexShrink: 0 }} />
          )}
          {!validating && inputValue && (
            <button
              type="button"
              onClick={() => { setInputValue(''); setValidation(null); onChange?.(''); }}
              style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: 'var(--text-secondary, #94a3b8)', display: 'flex', alignItems: 'center' }}
              aria-label="clear"
            >
              <X size={13} />
            </button>
          )}
        </div>

        {/* Dropdown */}
        {showDropdown && dropdownItems.length > 0 && (
          <div
            ref={dropdownRef}
            role="listbox"
            aria-label="local models"
            style={{
              position: 'absolute',
              top: 'calc(100% + 4px)',
              left: 0,
              right: 0,
              zIndex: 500,
              background: 'var(--bg-card, #0f172a)',
              border: '1px solid var(--border, #1f2937)',
              borderRadius: 8,
              maxHeight: 200,
              overflowY: 'auto',
              boxShadow: '0 10px 30px rgba(0,0,0,0.55)',
            }}
          >
            {loadingLocal ? (
              <div style={{ padding: '10px 14px', color: 'var(--text-secondary, #94a3b8)', fontSize: 12 }}>
                Loading local models…
              </div>
            ) : (
              dropdownItems.map((id) => (
                <button
                  key={id}
                  type="button"
                  role="option"
                  aria-selected={inputValue === id}
                  onClick={() => selectModel(id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    width: '100%',
                    padding: '8px 14px',
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    color: 'var(--text-primary, #f1f5f9)',
                    fontSize: 12,
                    fontFamily: "'JetBrains Mono', monospace",
                    textAlign: 'left',
                    transition: 'background 0.1s',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-elevated, #1a2235)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'none'; }}
                >
                  <Check size={12} style={{ color: 'var(--color-success, #4ade80)', opacity: inputValue === id ? 1 : 0, flexShrink: 0 }} />
                  {id}
                </button>
              ))
            )}
          </div>
        )}
      </div>

      {/* Size presets */}
      {showPresets && (
        <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 6 }}>
          <span style={{ fontSize: 11, color: 'var(--text-secondary, #94a3b8)', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
            Presets
          </span>
          {SIZE_PRESETS.map((p) => (
            <button
              key={p.id}
              type="button"
              disabled={disabled}
              onClick={() => {
                setInputValue(p.id);
                setValidation(null);
                if (debounceRef.current) clearTimeout(debounceRef.current);
                debounceRef.current = setTimeout(() => triggerValidation(p.id), DEBOUNCE_MS);
                onChange?.(p.id);
              }}
              title={p.id}
              style={{
                padding: '3px 10px',
                borderRadius: 12,
                border: '1px solid var(--border, #1f2937)',
                background: inputValue === p.id ? 'rgba(118,185,0,0.12)' : 'var(--bg-card, #0f172a)',
                color: inputValue === p.id ? '#76b900' : 'var(--text-secondary, #94a3b8)',
                fontSize: 11,
                cursor: disabled ? 'not-allowed' : 'pointer',
                fontFamily: "var(--font-ui, 'Outfit', sans-serif)",
                opacity: disabled ? 0.5 : 1,
                borderColor: inputValue === p.id ? 'rgba(118,185,0,0.4)' : 'var(--border, #1f2937)',
                transition: 'all 0.15s',
              }}
            >
              {p.label}
            </button>
          ))}
        </div>
      )}

      {/* Memory estimate card */}
      {showMemoryEstimate && validation?.valid === true && (
        <div
          style={{
            padding: '12px 14px',
            background: 'var(--bg-card, #0f172a)',
            border: '1px solid var(--border, #1f2937)',
            borderRadius: 8,
            display: 'flex',
            flexDirection: 'column',
            gap: 10,
          }}
        >
          {/* Header row: model id + badges */}
          <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 12,
                color: 'var(--text-primary, #f1f5f9)',
                wordBreak: 'break-all',
              }}
            >
              {validation.model_id}
            </span>
            {validation.gated && (
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  padding: '2px 7px',
                  borderRadius: 10,
                  background: 'rgba(245,158,11,0.15)',
                  border: '1px solid rgba(245,158,11,0.35)',
                  color: '#f59e0b',
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: '0.06em',
                  textTransform: 'uppercase',
                }}
              >
                <AlertTriangle size={10} />
                Gated by HF
              </span>
            )}
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                padding: '2px 7px',
                borderRadius: 10,
                background: validation.fits_128gb ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)',
                border: `1px solid ${validation.fits_128gb ? 'rgba(34,197,94,0.35)' : 'rgba(239,68,68,0.35)'}`,
                color: validation.fits_128gb ? 'var(--color-success, #4ade80)' : 'var(--color-error, #f87171)',
                fontSize: 10,
                fontWeight: 700,
                letterSpacing: '0.06em',
                textTransform: 'uppercase',
              }}
            >
              {validation.fits_128gb ? <Check size={10} /> : <X size={10} />}
              {validation.fits_128gb ? 'Fits 128 GB' : 'Exceeds 128 GB'}
            </span>
          </div>

          {/* Memory estimate */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 11, color: 'var(--text-secondary, #94a3b8)', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
              Est. peak memory
            </span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, color: 'var(--text-primary, #f1f5f9)', fontWeight: 600 }}>
              {typeof validation.estimated_memory_gb === 'number'
                ? `${validation.estimated_memory_gb.toFixed(2)} GB`
                : '—'}
            </span>
          </div>

          {/* LoRA target modules */}
          {validation.lora_target_modules?.length > 0 && (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 6 }}>
                <span style={{ fontSize: 11, color: 'var(--text-secondary, #94a3b8)', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                  LoRA target modules
                </span>
                <InfoTooltip info={CONCEPT_INFO.lora} />
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                {validation.lora_target_modules.map((mod) => (
                  <span
                    key={mod}
                    style={{
                      padding: '2px 8px',
                      borderRadius: 4,
                      background: 'var(--bg-elevated, #1a2235)',
                      border: '1px solid var(--border, #1f2937)',
                      fontFamily: "'JetBrains Mono', monospace",
                      fontSize: 11,
                      color: 'var(--text-secondary, #94a3b8)',
                    }}
                  >
                    {mod}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Pull button */}
          {showPull && (
            <button
              type="button"
              disabled={pulling || disabled}
              onClick={handlePull}
              style={{
                alignSelf: 'flex-start',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '6px 14px',
                borderRadius: 6,
                border: '1px solid rgba(118,185,0,0.4)',
                background: 'rgba(118,185,0,0.10)',
                color: '#76b900',
                fontSize: 12,
                fontWeight: 600,
                cursor: pulling || disabled ? 'not-allowed' : 'pointer',
                opacity: pulling || disabled ? 0.7 : 1,
                fontFamily: "var(--font-ui, 'Outfit', sans-serif)",
                transition: 'background 0.15s, box-shadow 0.15s',
              }}
              onMouseEnter={(e) => {
                if (!pulling && !disabled) e.currentTarget.style.background = 'rgba(118,185,0,0.18)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'rgba(118,185,0,0.10)';
              }}
            >
              {pulling ? (
                <Loader size={13} style={{ animation: 'mf-spin 1s linear infinite' }} />
              ) : (
                <Download size={13} />
              )}
              {pulling ? 'Pulling…' : 'Pull to Ollama'}
            </button>
          )}
        </div>
      )}

      {/* Validation failed notice */}
      {validation?.valid === false && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '8px 12px',
            background: 'rgba(239,68,68,0.08)',
            border: '1px solid rgba(239,68,68,0.25)',
            borderRadius: 8,
            fontSize: 12,
            color: 'var(--color-error, #f87171)',
          }}
        >
          <AlertTriangle size={13} />
          {validation.reason === 'not_found'
            ? `Model "${validation.model_id}" not found on HuggingFace.`
            : `Could not validate model (${validation.reason || 'error'}).`}
        </div>
      )}

      {/* Spin keyframe (inline so it works without a global stylesheet change) */}
      <style>{`@keyframes mf-spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

function isLocalModel(modelId, localModels) {
  if (!modelId) return false;
  const lower = modelId.toLowerCase();
  return localModels.some((id) => id.toLowerCase() === lower);
}
