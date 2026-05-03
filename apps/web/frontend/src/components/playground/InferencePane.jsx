import { useState, useEffect, useRef } from 'react';
import { Send, RotateCcw, Zap } from 'lucide-react';
import { apiFetch } from '../../config/api';
import DNALoader from '../shared/DNALoader';
import MagneticButton from '../shared/MagneticButton';

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
  }, [text]);

  return (
    <span>
      {displayed}
      {displayed.length < text.length && (
        <span className="animate-cursor" style={{ borderRight: '1px solid #76b900', marginLeft: 1 }} />
      )}
    </span>
  );
}

const MOCK_RESPONSES = {
  base: 'This is a response from the base model. It provides a foundational answer based on pre-training data without any evolutionary improvements applied. The answer may lack precision on specialized topics.',
  champion: 'This is the champion model response — Generation 23, the highest-performing checkpoint. Evolutionary Score Distillation™ has refined this model across 23 generations of adversarial probing and score-weighted mutation, yielding measurably superior accuracy on reasoning benchmarks.',
};

export default function InferencePane() {
  const [prompt, setPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const [responses, setResponses] = useState({ base: '', champion: '' });
  const [submitted, setSubmitted] = useState(false);
  const textareaRef = useRef(null);

  async function handleSubmit() {
    if (!prompt.trim() || loading) return;
    setLoading(true);
    setSubmitted(false);
    setResponses({ base: '', champion: '' });

    const result = await apiFetch('/infer', {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    });

    if (result) {
      setResponses({ base: result.base || MOCK_RESPONSES.base, champion: result.champion || MOCK_RESPONSES.champion });
    } else {
      setResponses({
        base: `[Mock] ${MOCK_RESPONSES.base} Prompt: "${prompt.slice(0, 50)}..."`,
        champion: `[Mock] ${MOCK_RESPONSES.champion} Prompt: "${prompt.slice(0, 50)}..."`,
      });
    }
    setLoading(false);
    setSubmitted(true);
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit();
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 16 }}>
      {/* Prompt */}
      <div style={{
        background: '#111827',
        border: '1px solid #1e293b',
        borderRadius: 12,
        padding: 16,
      }}>
        <div style={{ fontSize: 11, color: '#64748b', fontFamily: 'JetBrains Mono', letterSpacing: 2, marginBottom: 10 }}>
          PROMPT
        </div>
        <textarea
          ref={textareaRef}
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
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
          onFocus={e => e.target.style.borderColor = '#818cf8'}
          onBlur={e => e.target.style.borderColor = '#1e293b'}
        />
        <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', gap: 6, flex: 1, flexWrap: 'wrap' }}>
            {EXAMPLE_PROMPTS.map((p, i) => (
              <button
                key={i}
                onClick={() => setPrompt(p)}
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
                onMouseEnter={e => { e.currentTarget.style.borderColor = '#334155'; e.currentTarget.style.color = '#94a3b8'; }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = '#1e293b'; e.currentTarget.style.color = '#64748b'; }}
              >
                {p.slice(0, 30)}…
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={() => { setPrompt(''); setSubmitted(false); setResponses({ base: '', champion: '' }); }}
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
                <><DNALoader size={14} /> Running…</>
              ) : (
                <><Zap size={13} /> Run Inference</>
              )}
            </MagneticButton>
          </div>
        </div>
      </div>

      {/* Side-by-side responses */}
      {(submitted || loading) && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, flex: 1 }}>
          {[
            { key: 'base', label: 'BASE MODEL', color: '#818cf8', subtitle: 'Pre-evolution checkpoint' },
            { key: 'champion', label: 'CHAMPION MODEL', color: '#76b900', subtitle: 'Gen 23 — best evolved', crown: true },
          ].map(({ key, label, color, subtitle, crown }) => (
            <div key={key} style={{
              background: '#111827',
              border: `1px solid ${loading ? '#1e293b' : color + '33'}`,
              borderRadius: 12,
              padding: 16,
              transition: 'border-color 400ms',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
                <div>
                  <div style={{ fontSize: 10, fontFamily: 'JetBrains Mono', color, letterSpacing: 1 }}>{label}</div>
                  <div style={{ fontSize: 12, color: '#64748b', fontFamily: 'Outfit', marginTop: 2 }}>{subtitle}</div>
                </div>
                {crown && <span style={{ fontSize: 20, animation: 'crown-float 3s ease-in-out infinite' }}>👑</span>}
              </div>
              <div style={{
                minHeight: 120,
                fontSize: 13,
                lineHeight: 1.7,
                color: '#94a3b8',
                fontFamily: 'Outfit',
              }}>
                {loading ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '20px 0' }}>
                    <DNALoader size={24} />
                    <span style={{ color: '#475569', fontSize: 12, fontFamily: 'JetBrains Mono' }}>Generating…</span>
                  </div>
                ) : responses[key] ? (
                  <TypewriterText text={responses[key]} speed={key === 'champion' ? 18 : 22} />
                ) : null}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
