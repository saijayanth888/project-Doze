import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { C, F } from '../config/colors';
import MFLogo from '../components/shared/MFLogo';

const TICKER_ITEMS = ['Generation 25','Champion Score: 0.823','Models Evolved: 25','MMLU: 0.781','HumanEval: 0.612','GSM8K: 0.634','HellaSwag: 0.802','ARC: 0.714','Adapter: llama3.2-gen25','Run mf-a3b1 · Complete'];

const HOW_IT_WORKS = [
  { n: '01', label: 'Evaluate',  desc: 'Score champion on MMLU, ARC-C, HellaSwag, GSM8K, HumanEval via batched eval.' },
  { n: '02', label: 'Identify',  desc: 'Agent analyzes weak categories. Model introspects its own reasoning gaps.' },
  { n: '03', label: 'Curate',    desc: 'Pull targeted datasets from HuggingFace or synthesize via self-improvement.' },
  { n: '04', label: 'Train',     desc: 'Fine-tune LoRA adapter on curated data. TRL + PEFT + DeepSpeed. Stacked adapters.' },
  { n: '05', label: 'Compare',   desc: 'Child vs parent on identical benchmarks. Promote if higher avg, no regressions.' },
  { n: '06', label: 'Promote',   desc: 'Child wins → new champion. Adapter saved. Lineage recorded. Loop continues.' },
];

const METHODS = [
  'Evolutionary Score Distillation™',
  'Adversarial Benchmark Probing™',
  'Lineage-Aware Gradient Shaping™',
  'Champion Retention Protocol™',
  'Score-Weighted Mutation™',
];

function MagBtn({ children, onClick, variant = 'primary', size = 'lg' }) {
  const ref = useRef();
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const onMove = e => {
    const r = ref.current.getBoundingClientRect();
    setPos({ x: (e.clientX - r.left - r.width / 2) * 0.12, y: (e.clientY - r.top - r.height / 2) * 0.12 });
  };
  const sizes = { sm: { padding: '7px 16px', fontSize: 13 }, md: { padding: '10px 22px', fontSize: 14 }, lg: { padding: '13px 30px', fontSize: 15 } };
  const vars = {
    primary: { background: C.acc, color: '#000', border: 'none', boxShadow: `0 0 28px ${C.accGlow}` },
    ghost:   { background: 'transparent', color: C.txtP, border: `1px solid ${C.border}`, boxShadow: 'none' },
  };
  return (
    <button ref={ref} onClick={onClick} onMouseMove={onMove} onMouseLeave={() => setPos({ x: 0, y: 0 })}
      style={{ ...sizes[size], ...vars[variant], borderRadius: 6, cursor: 'pointer', fontFamily: F.ui, fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 8, transition: 'all 150ms', transform: `translate(${pos.x}px,${pos.y}px)`, willChange: 'transform' }}>
      {children}
    </button>
  );
}

function MeshBg() {
  return (
    <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', zIndex: 0 }}>
      <div style={{ position: 'absolute', width: '70%', height: '70%', top: '-10%', left: '30%', borderRadius: '50%', background: 'radial-gradient(ellipse,rgba(118,185,0,.07) 0%,transparent 70%)', animation: 'mesh-drift-1 45s ease-in-out infinite' }} />
      <div style={{ position: 'absolute', width: '80%', height: '80%', top: '10%', left: '-20%', borderRadius: '50%', background: 'radial-gradient(ellipse,rgba(129,140,248,.09) 0%,transparent 70%)', animation: 'mesh-drift-2 55s ease-in-out infinite' }} />
      <div style={{ position: 'absolute', width: '60%', height: '60%', bottom: '-10%', right: '10%', borderRadius: '50%', background: 'radial-gradient(ellipse,rgba(192,132,252,.06) 0%,transparent 70%)', animation: 'mesh-drift-3 50s ease-in-out infinite' }} />
      <div style={{ position: 'absolute', inset: 0, backgroundImage: 'radial-gradient(circle,rgba(71,85,105,.22) 1px,transparent 1px)', backgroundSize: '22px 22px' }} />
    </div>
  );
}

function TypingHeadline({ onDone }) {
  const FULL = 'Models That Evolve Themselves';
  const [typed, setTyped] = useState('');
  const [showCursor, setShowCursor] = useState(true);
  const [done, setDone] = useState(false);

  useEffect(() => {
    let i = 0;
    const iv = setInterval(() => {
      setTyped(FULL.slice(0, i + 1));
      i++;
      if (i >= FULL.length) {
        clearInterval(iv);
        let b = 0;
        const biv = setInterval(() => {
          setShowCursor(s => !s);
          b++;
          if (b >= 6) { clearInterval(biv); setDone(true); setShowCursor(false); onDone?.(); }
        }, 300);
      }
    }, 55);
    return () => clearInterval(iv);
  }, []);

  const words = typed.split(' ');
  const isComplete = typed.length === FULL.length;
  return (
    <h1 style={{ fontFamily: F.display, fontSize: 'clamp(2.4rem,6vw,4.8rem)', fontWeight: 400, lineHeight: 1.1, letterSpacing: '-0.02em', color: C.txtP, marginBottom: 20 }}>
      {words.map((word, wi) => {
        const isGrad = isComplete && wi >= words.length - 3;
        return (
          <span key={wi} style={{ display: 'inline', background: isGrad ? C.evo : undefined, WebkitBackgroundClip: isGrad ? 'text' : undefined, WebkitTextFillColor: isGrad ? 'transparent' : undefined }}>
            {word}{wi < words.length - 1 ? ' ' : ''}
          </span>
        );
      })}
      {!done && <span style={{ opacity: showCursor ? 1 : 0, fontFamily: F.mono, fontWeight: 300 }}>|</span>}
    </h1>
  );
}

export default function LandingPage() {
  const navigate = useNavigate();
  const [subVisible, setSubVisible] = useState(false);
  const [howVisible, setHowVisible] = useState(false);
  const howRef = useRef();

  useEffect(() => {
    const obs = new IntersectionObserver(([e]) => { if (e.isIntersecting) setHowVisible(true); }, { threshold: 0.1 });
    if (howRef.current) obs.observe(howRef.current);
    return () => obs.disconnect();
  }, []);

  return (
    <div style={{ background: C.bg, minHeight: '100vh' }}>
      {/* Nav */}
      <nav style={{ position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100, background: 'rgba(6,8,13,0.85)', backdropFilter: 'blur(12px)', borderBottom: `1px solid ${C.border}` }}>
        <div style={{ maxWidth: 1140, margin: '0 auto', padding: '0 24px', height: 56, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <MFLogo size={26} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
            {['How It Works', 'Architecture'].map(item => (
              <a key={item} href={`#${item.toLowerCase().replace(/ /g, '-')}`} style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM, textDecoration: 'none' }}>{item}</a>
            ))}
            <MagBtn size="sm" onClick={() => navigate('/dashboard')}>Dashboard →</MagBtn>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section style={{ minHeight: '100vh', position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', paddingTop: 56, overflow: 'hidden' }}>
        <MeshBg />
        <div style={{ position: 'relative', zIndex: 1, textAlign: 'center', maxWidth: 900, padding: '0 24px' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, background: 'rgba(118,185,0,.08)', border: `1px solid rgba(118,185,0,.25)`, borderRadius: 9999, padding: '5px 14px 5px 10px', marginBottom: 28, animation: 'fade-up .5s ease-out both' }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: C.acc, animation: 'mf-pulse 1.5s infinite', display: 'inline-block' }} />
            <span style={{ fontFamily: F.mono, fontSize: 11, color: C.acc, fontWeight: 600, letterSpacing: '0.06em' }}>GENERATION 25 · LIVE</span>
          </div>
          <TypingHeadline onDone={() => setTimeout(() => setSubVisible(true), 200)} />
          <p style={{ fontFamily: F.mono, fontSize: 'clamp(.8rem,1.3vw,.95rem)', color: C.txtS, lineHeight: 1.8, marginBottom: 36, opacity: subVisible ? 1 : 0, transform: subVisible ? 'none' : 'translateY(10px)', transition: 'opacity .5s,transform .5s' }}>
            Autonomous LLM evolution engine.<br />
            <span style={{ color: C.txtP }}>Spawn.</span> <span style={{ color: C.acc }}>Train.</span> <span style={{ color: C.ind }}>Evaluate.</span> <span style={{ color: '#c084fc' }}>Promote.</span> Repeat.
          </p>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap', opacity: subVisible ? 1 : 0, transition: 'opacity .6s .2s', marginBottom: 52 }}>
            <MagBtn onClick={() => navigate('/dashboard')}>View Dashboard →</MagBtn>
            <MagBtn variant="ghost">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>
              GitHub ⭐
            </MagBtn>
          </div>
          <div style={{ display: 'flex', gap: 36, justifyContent: 'center', flexWrap: 'wrap', opacity: subVisible ? 1 : 0, transition: 'opacity .7s .4s' }}>
            {[{ val: '25', label: 'Generations' }, { val: '0.823', label: 'Champion Score' }, { val: '15/25', label: 'Promotions' }, { val: 'DGX Spark', label: 'Target Hardware' }].map(({ val, label }) => (
              <div key={label} style={{ textAlign: 'center' }}>
                <div style={{ fontFamily: F.mono, fontSize: '1.7rem', fontWeight: 600, color: C.acc, lineHeight: 1 }}>{val}</div>
                <div style={{ fontFamily: F.ui, fontSize: 10, color: C.txtM, marginTop: 4, letterSpacing: '0.06em', textTransform: 'uppercase' }}>{label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Ticker */}
      <div style={{ background: C.bgS, borderTop: `1px solid ${C.border}`, borderBottom: `1px solid ${C.border}`, padding: '10px 0', overflow: 'hidden' }}>
        <div style={{ display: 'flex', width: 'max-content', animation: 'ticker-scroll 30s linear infinite', willChange: 'transform' }}>
          {[...TICKER_ITEMS, ...TICKER_ITEMS].map((item, i) => (
            <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '0 28px', fontFamily: F.mono, fontSize: 12, color: C.txtS, whiteSpace: 'nowrap' }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: C.acc, display: 'inline-block', animation: 'mf-pulse 2s ease-in-out infinite' }} />
              {item}
            </span>
          ))}
        </div>
      </div>

      {/* How It Works */}
      <section id="how-it-works" style={{ background: C.bgS, borderTop: `1px solid ${C.border}`, padding: '80px 0' }} ref={howRef}>
        <div style={{ maxWidth: 1100, margin: '0 auto', padding: '0 24px' }}>
          <div style={{ textAlign: 'center', marginBottom: 48 }}>
            <div style={{ fontFamily: F.mono, fontSize: 11, color: C.acc, letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10 }}>The Evolution Loop</div>
            <h2 style={{ fontFamily: F.display, fontSize: 'clamp(1.8rem,3.5vw,2.8rem)', fontWeight: 400, color: C.txtP }}>Six steps. Infinite improvement.</h2>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 1, background: C.border, borderRadius: 10, overflow: 'hidden' }}>
            {HOW_IT_WORKS.map((step, i) => (
              <div key={step.label} style={{ background: C.bgS, padding: '26px 22px', animation: howVisible ? `slide-up-stagger .4s ease-out ${i * 80}ms both` : 'none', cursor: 'default' }}
                onMouseEnter={e => e.currentTarget.style.background = C.bgC}
                onMouseLeave={e => e.currentTarget.style.background = C.bgS}>
                <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, fontWeight: 600, marginBottom: 10 }}>{step.n}</div>
                <div style={{ fontFamily: F.ui, fontSize: 16, fontWeight: 600, color: C.txtP, marginBottom: 7 }}>{step.label}</div>
                <div style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM, lineHeight: 1.65 }}>{step.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Protected Innovation */}
      <section style={{ background: C.bg, borderTop: `1px solid ${C.border}`, padding: '80px 0' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto', padding: '0 24px' }}>
          <div style={{ textAlign: 'center', marginBottom: 48 }}>
            <span style={{ fontFamily: F.mono, fontSize: 9, color: C.gold, background: C.goldDim, border: `1px solid ${C.goldBorder}`, padding: '3px 10px', borderRadius: 3, letterSpacing: '0.1em', animation: 'float-badge 4s ease-in-out infinite', display: 'inline-block', marginBottom: 16 }}>PAT. PEND.</span>
            <h2 style={{ fontFamily: F.display, fontSize: 'clamp(1.8rem,3.5vw,2.8rem)', fontWeight: 400, color: C.txtP }}>Protected Innovation</h2>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))', gap: 12 }}>
            {METHODS.map(method => (
              <div key={method} style={{ background: C.bgC, border: `1px solid ${C.goldBorder}`, borderRadius: 8, padding: '16px', display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                <span style={{ fontFamily: F.mono, fontSize: 9, color: C.gold, background: C.goldDim, border: `1px solid ${C.goldBorder}`, padding: '2px 6px', borderRadius: 3, flexShrink: 0, marginTop: 2 }}>TM</span>
                <span style={{ fontFamily: F.ui, fontSize: 13, color: C.txtS, lineHeight: 1.5 }}>{method}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer style={{ background: C.bgS, borderTop: `1px solid ${C.border}`, padding: '28px 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <MFLogo size={22} />
        <span style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM }}>© 2025 ModelForge</span>
        <span style={{ fontFamily: F.mono, fontSize: 9, color: C.gold, background: C.goldDim, border: `1px solid ${C.goldBorder}`, padding: '2px 8px', borderRadius: 3, letterSpacing: '0.1em' }}>PAT. PEND.</span>
      </footer>
    </div>
  );
}
