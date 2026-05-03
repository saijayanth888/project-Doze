import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Shield, Code2, Building2, Lock } from 'lucide-react';
import { C, F } from '../config/colors';
import MFLogo from '../components/shared/MFLogo';
import LandingArchitecture from '../components/landing/LandingArchitecture';

const NOISE_BG = `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E")`;

const TICKER_ITEMS = [
  'Generation 47', 'Champion Score: 0.847', 'Models Evolved: 312', 'Adapters Active: 8', 'Training Samples: 127K',
  'Last Evolution: 2h ago', 'Avg Gen Time: 43m', 'Discarded: 265', 'MMLU: 0.803', 'HumanEval: 0.612',
  'Run a3b1 · Active', 'Base: Llama 3.1 8B',
];

const HOW_IT_WORKS = [
  { n: '01', label: 'Evaluate', desc: 'Score champion on MMLU, ARC-C, HellaSwag, GSM8K, HumanEval via vLLM batched eval.' },
  { n: '02', label: 'Identify', desc: 'Agent analyzes weak categories. Champion model introspects its own reasoning gaps.' },
  { n: '03', label: 'Curate', desc: 'Pull targeted datasets from HuggingFace or synthesize data using the model itself.' },
  { n: '04', label: 'Train', desc: 'Fine-tune LoRA adapter (child) on curated data. TRL + PEFT + DeepSpeed. Stacked adapters.' },
  { n: '05', label: 'Compare', desc: 'Child vs parent on identical benchmarks. Promotion: higher avg, no regressions, weak improvement.' },
  { n: '06', label: 'Promote', desc: 'Child wins → becomes new champion. Adapter saved. Lineage recorded. Loop continues.' },
];

const TECH = [
  { l: 'LangGraph', c: C.acc }, { l: 'Ollama', c: C.ind }, { l: 'vLLM', c: '#38bdf8' }, { l: 'PostgreSQL', c: C.txtS },
  { l: 'pgvector', c: '#c084fc' }, { l: 'n8n', c: C.warning }, { l: 'TRL+PEFT', c: '#f472b6' }, { l: 'DeepSpeed', c: C.success },
];

const INNOVATION_PILLARS = [
  { Icon: Shield, title: 'Provisional Patent Filed', desc: 'Autonomous model evolution loop with fitness-based selection and self-targeted data curation.', gold: true },
  { Icon: Code2, title: 'Open Core Licensed', desc: 'Framework is open source. The proprietary evolution engine is commercially licensed.', gold: false },
  { Icon: Building2, title: 'Enterprise Ready', desc: 'Built for regulated industries. Model lineage tracking meets compliance requirements.', gold: false },
];

function MagBtn({ children, onClick, variant = 'primary', size = 'lg', type = 'button', href }) {
  const ref = useRef();
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [ripple, setRipple] = useState(null);
  const onMove = e => {
    if (!ref.current) return;
    const r = ref.current.getBoundingClientRect();
    setPos({ x: (e.clientX - r.left - r.width / 2) * 0.14, y: (e.clientY - r.top - r.height / 2) * 0.14 });
  };
  const onClick2 = e => {
    if (ref.current) {
      const r = ref.current.getBoundingClientRect();
      setRipple({ x: e.clientX - r.left, y: e.clientY - r.top, id: Date.now() });
      setTimeout(() => setRipple(null), 700);
    }
    onClick?.(e);
  };
  const sizes = {
    sm: { padding: '6px 14px', fontSize: 13 },
    md: { padding: '11px 22px', fontSize: 14 },
    lg: { padding: '14px 32px', fontSize: 16 },
  };
  const variants = {
    primary: { background: C.acc, color: '#000', border: `1px solid ${C.acc}`, boxShadow: '0 0 28px rgba(118,185,0,.35)' },
    ghost: { background: 'transparent', color: C.txtP, border: `1px solid ${C.border}`, boxShadow: 'none' },
    outline: { background: 'transparent', color: C.ind, border: '1px solid rgba(129,140,248,.4)', boxShadow: 'none' },
  };
  const base = {
    position: 'relative', overflow: 'hidden', borderRadius: 6, cursor: 'pointer', fontFamily: F.ui, fontWeight: 600,
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8, transition: 'all 150ms', outline: 'none',
    transform: `translate(${pos.x}px,${pos.y}px)`, willChange: 'transform', textDecoration: 'none',
  };
  if (href) {
    return (
      <a ref={ref} href={href} onClick={onClick2} onMouseMove={onMove} onMouseLeave={() => setPos({ x: 0, y: 0 })} style={{ ...base, ...sizes[size], ...variants[variant] }}>
        {ripple && (
          <span key={ripple.id} style={{ position: 'absolute', left: ripple.x - 20, top: ripple.y - 20, width: 40, height: 40, borderRadius: '50%', background: 'rgba(255,255,255,.2)', animation: 'fade-up .7s ease-out forwards', pointerEvents: 'none' }} />
        )}
        {children}
      </a>
    );
  }
  return (
    <button ref={ref} type={type} onClick={onClick2} onMouseMove={onMove} onMouseLeave={() => setPos({ x: 0, y: 0 })} style={{ ...base, ...sizes[size], ...variants[variant] }}>
      {ripple && (
        <span key={ripple.id} style={{ position: 'absolute', left: ripple.x - 20, top: ripple.y - 20, width: 40, height: 40, borderRadius: '50%', background: 'rgba(255,255,255,.2)', animation: 'fade-up .7s ease-out forwards', pointerEvents: 'none' }} />
      )}
      {children}
    </button>
  );
}

function MeshBg() {
  return (
    <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', zIndex: 0 }}>
      <div style={{ position: 'absolute', width: '70%', height: '70%', top: '-10%', left: '30%', borderRadius: '50%', background: 'radial-gradient(ellipse,rgba(118,185,0,.07) 0%,transparent 70%)', animation: 'mesh-drift-1 45s ease-in-out infinite', willChange: 'transform' }} />
      <div style={{ position: 'absolute', width: '80%', height: '80%', top: '10%', left: '-20%', borderRadius: '50%', background: 'radial-gradient(ellipse,rgba(129,140,248,.09) 0%,transparent 70%)', animation: 'mesh-drift-2 55s ease-in-out infinite', willChange: 'transform' }} />
      <div style={{ position: 'absolute', width: '60%', height: '60%', bottom: '-10%', right: '10%', borderRadius: '50%', background: 'radial-gradient(ellipse,rgba(192,132,252,.06) 0%,transparent 70%)', animation: 'mesh-drift-3 50s ease-in-out infinite', willChange: 'transform' }} />
      <div style={{ position: 'absolute', width: '50%', height: '50%', bottom: '20%', left: '25%', borderRadius: '50%', background: 'radial-gradient(ellipse,rgba(244,114,182,.04) 0%,transparent 70%)', animation: 'mesh-drift-4 40s ease-in-out infinite', willChange: 'transform' }} />
      <div style={{ position: 'absolute', inset: 0, backgroundImage: 'radial-gradient(circle,rgba(71,85,105,.22) 1px,transparent 1px)', backgroundSize: '22px 22px' }} />
      <div style={{ position: 'absolute', inset: 0, opacity: 0.03, backgroundImage: NOISE_BG }} />
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
          if (b >= 6) {
            clearInterval(biv);
            setDone(true);
            setShowCursor(false);
            onDone?.();
          }
        }, 300);
      }
    }, 58);
    return () => clearInterval(iv);
  }, []);

  const words = typed.split(' ');
  const isComplete = typed.length === FULL.length;

  return (
    <h1 style={{ fontFamily: F.display, fontSize: 'clamp(2.6rem,6.5vw,5rem)', fontWeight: 400, lineHeight: 1.1, letterSpacing: '-0.02em', color: C.txtP, marginBottom: 22, minHeight: '1.1em' }}>
      {words.map((word, wi) => {
        const isGrad = wi >= words.length - 3 && isComplete;
        return (
          <span key={wi} style={{ display: 'inline', background: isGrad ? C.evo : undefined, WebkitBackgroundClip: isGrad ? 'text' : undefined, WebkitTextFillColor: isGrad ? 'transparent' : undefined }}>
            {word}{wi < words.length - 1 ? ' ' : ''}
          </span>
        );
      })}
      {!done && <span style={{ opacity: showCursor ? 1 : 0, fontFamily: F.mono, fontWeight: 300, transition: 'opacity 50ms' }}>|</span>}
    </h1>
  );
}

function PatentBadge({ style = {} }) {
  return (
    <span style={{ fontFamily: F.mono, fontSize: 9, fontWeight: 600, color: C.gold, background: 'rgba(212,165,116,.08)', border: '1px solid rgba(212,165,116,.3)', padding: '2px 7px', borderRadius: 3, letterSpacing: '0.1em', animation: 'float-badge 4s ease-in-out infinite', ...style }}>
      PAT. PEND.
    </span>
  );
}

function PropMethodPill({ label, desc }) {
  const [show, setShow] = useState(false);
  return (
    <div style={{ position: 'relative' }} onMouseEnter={() => setShow(true)} onMouseLeave={() => setShow(false)}>
      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '5px 12px', background: 'rgba(212,165,116,.06)', border: '1px solid rgba(212,165,116,.25)', borderRadius: 9999, cursor: 'default' }}>
        <Lock size={10} stroke={C.gold} strokeWidth={2} />
        <span style={{ fontFamily: F.mono, fontSize: 10, color: C.gold }}>{label}</span>
      </div>
      {show && (
        <div style={{ position: 'absolute', bottom: '120%', left: '50%', transform: 'translateX(-50%)', background: C.bgE, border: '1px solid rgba(212,165,116,.3)', borderRadius: 6, padding: '7px 12px', fontFamily: F.ui, fontSize: 11, color: C.gold, whiteSpace: 'nowrap', zIndex: 99, boxShadow: '0 8px 32px rgba(0,0,0,.5)' }}>
          {desc}
        </div>
      )}
    </div>
  );
}

export default function LandingPage() {
  const navigate = useNavigate();
  const [subVisible, setSubVisible] = useState(false);
  const [howVisible, setHowVisible] = useState(false);
  const [innovVisible, setInnovVisible] = useState(false);
  const [navScrolled, setNavScrolled] = useState(false);
  const [tickerPaused, setTickerPaused] = useState(false);
  const howRef = useRef();
  const innovRef = useRef();

  const githubUrl = import.meta.env.VITE_GITHUB_URL || 'https://github.com';

  useEffect(() => {
    const onScroll = () => setNavScrolled(window.scrollY > 40);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => {
    const obs = new IntersectionObserver(([e]) => { if (e.isIntersecting) setHowVisible(true); }, { threshold: 0.15 });
    if (howRef.current) obs.observe(howRef.current);
    return () => obs.disconnect();
  }, []);

  useEffect(() => {
    const obs = new IntersectionObserver(([e]) => { if (e.isIntersecting) setInnovVisible(true); }, { threshold: 0.2 });
    if (innovRef.current) obs.observe(innovRef.current);
    return () => obs.disconnect();
  }, []);

  const navLink = (e, enter) => {
    e.target.style.color = enter ? C.txtP : C.txtM;
  };

  return (
    <div style={{ background: C.bg, minHeight: '100vh' }}>
      <nav style={{
        position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100,
        background: navScrolled ? 'rgba(6,8,13,.92)' : 'transparent',
        backdropFilter: navScrolled ? 'blur(12px)' : 'none',
        borderBottom: navScrolled ? `1px solid ${C.border}` : '1px solid transparent',
        transition: 'all 300ms',
      }}
      >
        <div style={{ maxWidth: 1160, margin: '0 auto', padding: '0 24px', height: 58, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <MFLogo size={28} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
            {['Architecture', 'How It Works', 'Open Source'].map(item => (
              <a
                key={item}
                href={`#${item.toLowerCase().replace(/ /g, '-')}`}
                style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM, textDecoration: 'none', transition: 'color 150ms' }}
                onMouseEnter={e => navLink(e, true)}
                onMouseLeave={e => navLink(e, false)}
              >
                {item}
              </a>
            ))}
            <MagBtn size="sm" onClick={() => navigate('/dashboard')}>Dashboard →</MagBtn>
          </div>
        </div>
      </nav>

      <section style={{ minHeight: '100vh', position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', paddingTop: 58, overflow: 'hidden' }}>
        <MeshBg />
        <div style={{ position: 'relative', zIndex: 1, textAlign: 'center', maxWidth: 920, padding: '0 24px' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, background: 'rgba(118,185,0,.08)', border: '1px solid rgba(118,185,0,.25)', borderRadius: 9999, padding: '5px 14px 5px 10px', marginBottom: 28, animation: 'fade-up .5s ease-out both' }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: C.acc, animation: 'mf-pulse 1.5s infinite', boxShadow: `0 0 6px ${C.acc}88`, display: 'inline-block' }} />
            <span style={{ fontFamily: F.mono, fontSize: 11, color: C.acc, fontWeight: 600, letterSpacing: '0.06em' }}>GENERATION 47 · LIVE</span>
          </div>
          <TypingHeadline onDone={() => setTimeout(() => setSubVisible(true), 300)} />
          <p style={{ fontFamily: F.mono, fontSize: 'clamp(.8rem,1.4vw,1rem)', color: C.txtS, lineHeight: 1.75, maxWidth: 620, margin: '0 auto 38px', opacity: subVisible ? 1 : 0, transform: subVisible ? 'translateY(0)' : 'translateY(12px)', transition: 'opacity .5s ease-out,transform .5s ease-out' }}>
            Autonomous LLM evolution engine.<br />
            <span style={{ color: C.txtP }}>Spawn.</span> <span style={{ color: C.acc }}>Train.</span> <span style={{ color: C.ind }}>Evaluate.</span> <span style={{ color: '#c084fc' }}>Promote.</span> Repeat.
          </p>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap', opacity: subVisible ? 1 : 0, transition: 'opacity .6s ease-out .2s', marginBottom: 52 }}>
            <MagBtn size="lg" onClick={() => navigate('/dashboard')}>View Dashboard →</MagBtn>
            <MagBtn size="lg" variant="ghost" onClick={() => window.open(githubUrl, '_blank', 'noopener,noreferrer')}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" /></svg>
              Star on GitHub
            </MagBtn>
          </div>
          <div style={{ display: 'flex', gap: 36, justifyContent: 'center', flexWrap: 'wrap', opacity: subVisible ? 1 : 0, transition: 'opacity .7s ease-out .4s' }}>
            {[{ val: '47', label: 'Generations' }, { val: '0.847', label: 'Champion Score' }, { val: '23/47', label: 'Promotions' }, { val: '128GB', label: 'VRAM (DGX Spark)' }].map(({ val, label }) => (
              <div key={label} style={{ textAlign: 'center' }}>
                <div style={{ fontFamily: F.mono, fontSize: '1.7rem', fontWeight: 600, color: C.acc, lineHeight: 1 }}>{val}</div>
                <div style={{ fontFamily: F.ui, fontSize: 10, color: C.txtM, marginTop: 4, letterSpacing: '0.06em', textTransform: 'uppercase' }}>{label}</div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ position: 'absolute', bottom: 28, left: '50%', transform: 'translateX(-50%)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 5, opacity: 0.35 }}>
          <div style={{ fontFamily: F.mono, fontSize: 9, color: C.txtS, letterSpacing: '0.12em' }}>SCROLL</div>
          <div style={{ width: 1, height: 28, background: `linear-gradient(${C.txtM},transparent)` }} />
        </div>
      </section>

      <div
        style={{ background: C.bgS, borderTop: `1px solid ${C.border}`, borderBottom: `1px solid ${C.border}`, padding: '10px 0', overflow: 'hidden' }}
        onMouseEnter={() => setTickerPaused(true)}
        onMouseLeave={() => setTickerPaused(false)}
      >
        <div style={{ display: 'flex', width: 'max-content', animation: 'ticker-scroll 30s linear infinite', animationPlayState: tickerPaused ? 'paused' : 'running', willChange: 'transform' }}>
          {[...TICKER_ITEMS, ...TICKER_ITEMS].map((item, i) => (
            <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '0 28px', fontFamily: F.mono, fontSize: 12, color: C.txtS, whiteSpace: 'nowrap', flexShrink: 0 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: C.acc, boxShadow: `0 0 5px ${C.acc}88`, display: 'inline-block', animation: 'mf-pulse 2s ease-in-out infinite' }} />
              {item}
            </span>
          ))}
        </div>
      </div>

      <section id="how-it-works" style={{ background: C.bgS, borderTop: `1px solid ${C.border}`, padding: '80px 0' }} ref={howRef}>
        <div style={{ maxWidth: 1100, margin: '0 auto', padding: '0 24px' }}>
          <div style={{ textAlign: 'center', marginBottom: 48 }}>
            <div style={{ fontFamily: F.mono, fontSize: 11, color: C.acc, letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10 }}>The Evolution Loop</div>
            <h2 style={{ fontFamily: F.display, fontSize: 'clamp(1.8rem,3.5vw,2.8rem)', fontWeight: 400, color: C.txtP, lineHeight: 1.2 }}>Six steps. Infinite improvement.</h2>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 1, background: C.border, borderRadius: 10, overflow: 'hidden' }}>
            {HOW_IT_WORKS.map((step, i) => (
              <div
                key={step.label}
                style={{
                  background: C.bgS, padding: '26px 22px', transition: 'background 200ms', cursor: 'default',
                  animation: howVisible ? `slide-up-stagger .4s ease-out ${i * 80}ms both` : 'none', willChange: 'transform,opacity',
                }}
                onMouseEnter={e => { e.currentTarget.style.background = C.bgC; }}
                onMouseLeave={e => { e.currentTarget.style.background = C.bgS; }}
              >
                <div style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, fontWeight: 600, marginBottom: 10 }}>{step.n}</div>
                <div style={{ fontFamily: F.ui, fontSize: 16, fontWeight: 600, color: C.txtP, marginBottom: 7 }}>{step.label}</div>
                <div style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM, lineHeight: 1.65 }}>{step.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <LandingArchitecture />

      <section id="protected-innovation" style={{ background: C.bgS, borderTop: `1px solid ${C.border}`, padding: '72px 0', position: 'relative' }} ref={innovRef}>
        <div style={{ position: 'absolute', top: 20, right: 24 }}><PatentBadge /></div>
        <div style={{ maxWidth: 960, margin: '0 auto', padding: '0 24px' }}>
          <div style={{ textAlign: 'center', marginBottom: 40 }}>
            <div style={{ fontFamily: F.mono, fontSize: 11, color: C.gold, letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10 }}>IP Protection</div>
            <h2 style={{ fontFamily: F.display, fontSize: 'clamp(1.8rem,3.5vw,2.6rem)', fontWeight: 400, color: C.txtP, lineHeight: 1.3 }}>Protected Innovation</h2>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12 }}>
            {INNOVATION_PILLARS.map((p, i) => (
              <div
                key={p.title}
                style={{
                  background: C.bgC,
                  border: `1px solid ${p.gold ? 'rgba(212,165,116,.3)' : C.border}`,
                  borderRadius: 10,
                  padding: '24px 20px',
                  animation: innovVisible ? `slide-up-stagger .4s ease-out ${i * 100}ms both` : 'none',
                  willChange: 'transform,opacity',
                }}
              >
                <p.Icon size={24} strokeWidth={1.5} color={p.gold ? C.gold : C.txtS} style={{ marginBottom: 14 }} />
                <h3 style={{ fontFamily: F.ui, fontSize: 15, fontWeight: 700, color: p.gold ? C.gold : C.txtP, marginBottom: 8 }}>{p.title}</h3>
                <p style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM, lineHeight: 1.6, margin: 0 }}>{p.desc}</p>
                {p.gold && <div style={{ marginTop: 12 }}><PatentBadge /></div>}
              </div>
            ))}
          </div>
          <div style={{ marginTop: 28, display: 'flex', gap: 16, justifyContent: 'center', flexWrap: 'wrap' }}>
            {[
              { label: 'Autonomous Evolution Loop', desc: 'ModelForge proprietary method' },
              { label: 'Self-Targeted Data Curation', desc: 'ModelForge proprietary method' },
              { label: 'Fitness-Based Promotion Logic', desc: 'ModelForge proprietary method' },
            ].map(({ label, desc }) => (
              <PropMethodPill key={label} label={label} desc={desc} />
            ))}
          </div>
        </div>
      </section>

      <section id="open-source" style={{ background: C.bg, borderTop: `1px solid ${C.border}`, padding: '80px 0' }}>
        <div style={{ maxWidth: 900, margin: '0 auto', padding: '0 24px', textAlign: 'center' }}>
          <div style={{ fontFamily: F.mono, fontSize: 11, color: '#f472b6', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10 }}>Community</div>
          <h2 style={{ fontFamily: F.display, fontSize: 'clamp(1.6rem,3.2vw,2.5rem)', fontWeight: 400, color: C.txtP, marginBottom: 14, lineHeight: 1.3 }}>
            Built for the community.<br /><span style={{ fontStyle: 'italic', color: C.ind }}>Backed by patents.</span>
          </h2>
          <p style={{ fontFamily: F.ui, fontSize: 14, color: C.txtM, lineHeight: 1.7, maxWidth: 520, margin: '0 auto 28px' }}>
            ModelForge is the first open-source platform for autonomous LLM evolution. Spawn your own self-improving AI on consumer hardware or DGX-class infrastructure.
          </p>
          <div style={{ display: 'flex', gap: 14, justifyContent: 'center', marginBottom: 28, flexWrap: 'wrap' }}>
            {[{ icon: '★', val: '2,847', label: 'Stars' }, { icon: '⑂', val: '312', label: 'Forks' }, { icon: '●', val: '47', label: 'Contributors' }].map(({ icon, val, label }) => (
              <div key={label} style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: '13px 22px', display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 15, color: C.acc }}>{icon}</span>
                <div>
                  <div style={{ fontFamily: F.mono, fontSize: '1.05rem', fontWeight: 600, color: C.txtP, lineHeight: 1 }}>{val}</div>
                  <div style={{ fontFamily: F.ui, fontSize: 9, color: C.txtM, marginTop: 2, letterSpacing: '0.06em', textTransform: 'uppercase' }}>{label}</div>
                </div>
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 7, justifyContent: 'center', flexWrap: 'wrap', marginBottom: 32 }}>
            {TECH.map(({ l, c }) => (
              <span
                key={l}
                style={{ fontFamily: F.mono, fontSize: 11, color: c, padding: '4px 10px', background: `${c}12`, border: `1px solid ${c}35`, borderRadius: 4, fontWeight: 500, transition: 'transform 150ms,box-shadow 150ms', cursor: 'default', display: 'inline-block' }}
                onMouseEnter={e => { e.currentTarget.style.transform = 'scale(1.08)'; e.currentTarget.style.boxShadow = `0 0 10px ${c}44`; }}
                onMouseLeave={e => { e.currentTarget.style.transform = ''; e.currentTarget.style.boxShadow = ''; }}
              >
                {l}
              </span>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
            <MagBtn size="md" onClick={() => window.open(githubUrl, '_blank', 'noopener,noreferrer')}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" /></svg>
              Star on GitHub
            </MagBtn>
            <MagBtn size="md" variant="ghost" href={`${githubUrl}#readme`}>Read Docs</MagBtn>
            <MagBtn size="md" variant="outline" href="#protected-innovation">Patent Status →</MagBtn>
          </div>
        </div>
      </section>

      <footer style={{ background: C.bg, borderTop: `1px solid ${C.border}`, padding: '28px 24px', animation: 'fade-up .5s ease-out both' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 14 }}>
          <MFLogo size={22} />
          <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
            {[
              { label: 'GitHub', href: githubUrl },
              { label: 'Documentation', href: `${githubUrl}#readme` },
              { label: 'API Docs', href: import.meta.env.VITE_API_DOCS_URL || 'http://localhost:8001/docs' },
              { label: 'Patent Status', href: '#protected-innovation' },
            ].map(({ label, href }) => (
              <a key={label} href={href} style={{ fontFamily: F.ui, fontSize: 12, color: C.txtM, textDecoration: 'none', transition: 'color 150ms' }} onMouseEnter={e => { e.target.style.color = C.txtS; }} onMouseLeave={e => { e.target.style.color = C.txtM; }}>{label}</a>
            ))}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM }}>Built on DGX Spark</span>
            <span style={{ fontFamily: F.mono, fontSize: 10, color: C.acc, background: 'rgba(118,185,0,.1)', border: '1px solid rgba(118,185,0,.25)', padding: '2px 6px', borderRadius: 3, letterSpacing: '0.05em' }}>NVIDIA</span>
            <span style={{ fontFamily: F.mono, fontSize: 10, color: C.gold }}>Patent Pending · © 2026 ModelForge</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
