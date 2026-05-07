import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Crown,
  Dna,
  GitBranch,
  Pause,
  Play,
  RefreshCw,
  Sparkles,
  X,
  Zap,
} from 'lucide-react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { BENCH_COLORS, C, F } from '../config/colors';
import { apiFetch } from '../config/api';
import { BENCHMARK_INFO } from '../data/benchmarkInfo';
import InfoTooltip from '../components/shared/InfoTooltip';
import LoadingSkeleton from '../components/shared/LoadingSkeleton';

const POLL_MS = 4000;
const BENCHMARK_OPTIONS = ['mmlu', 'arc_challenge', 'hellaswag', 'gsm8k', 'humaneval'];
const STRATEGY_OPTIONS = ['uniform', 'layer_wise', 'random_swap'];

function fmtRel(ts) {
  if (!ts) return '—';
  const t = new Date(ts).getTime();
  const dt = (Date.now() - t) / 1000;
  if (dt < 60) return `${Math.floor(dt)}s ago`;
  if (dt < 3600) return `${Math.floor(dt / 60)}m ago`;
  return `${Math.floor(dt / 3600)}h ago`;
}

function memberTone(m) {
  if (m.status === 'champion') return { fg: '#d4a574', bg: 'rgba(212,165,116,0.10)', border: 'rgba(212,165,116,0.55)', label: 'champion' };
  if (m.status === 'eliminated') return { fg: C.txtM, bg: 'rgba(100,116,139,0.06)', border: 'rgba(100,116,139,0.30)', label: 'eliminated' };
  return { fg: C.acc, bg: 'rgba(118,185,0,0.06)', border: 'rgba(118,185,0,0.40)', label: 'alive' };
}

function MemberCard({ m, isSelected, onSelect }) {
  const tone = memberTone(m);
  const score = typeof m.avg_score === 'number' ? m.avg_score.toFixed(3) : '—';
  return (
    <button
      type="button"
      onClick={() => onSelect(m)}
      style={{
        textAlign: 'left',
        background: isSelected ? `${tone.fg}1f` : tone.bg,
        border: `1px solid ${isSelected ? tone.fg : tone.border}`,
        borderRadius: 8,
        padding: '10px 12px',
        cursor: 'pointer',
        opacity: m.status === 'eliminated' ? 0.55 : 1,
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        minHeight: 96,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontFamily: F.mono, fontSize: 11, color: C.txtP, fontWeight: 600 }}>
          {m.member_id}
        </span>
        {m.status === 'champion' ? <Crown size={11} color={tone.fg} /> : null}
      </div>
      <div style={{ fontFamily: F.mono, fontSize: 18, color: tone.fg, fontWeight: 500 }}>
        {score}
      </div>
      <div style={{ display: 'flex', gap: 3, alignItems: 'flex-end', height: 16 }}>
        {BENCHMARK_OPTIONS.map((b) => {
          const v = typeof m.scores?.[b] === 'number' ? m.scores[b] : 0;
          const has = typeof m.scores?.[b] === 'number';
          return (
            <div
              key={b}
              title={`${b}: ${has ? v.toFixed(3) : '—'}`}
              style={{
                flex: 1,
                height: `${Math.max(2, v * 100)}%`,
                background: BENCH_COLORS[b] || '#94a3b8',
                opacity: has ? 0.7 : 0.15,
                borderRadius: 1,
                cursor: 'help',
              }}
            />
          );
        })}
      </div>
      {m.parent_a && m.parent_b ? (
        <div style={{ fontFamily: F.mono, fontSize: 9, color: C.txtM }}>
          {m.parent_a} × {m.parent_b} · α={typeof m.crossover_alpha === 'number' ? m.crossover_alpha.toFixed(2) : '—'}
        </div>
      ) : (
        <div style={{ fontFamily: F.mono, fontSize: 9, color: C.txtM }}>seed adapter</div>
      )}
    </button>
  );
}

function CrossoverInspector({ child, members }) {
  const byId = useMemo(() => Object.fromEntries(members.map((m) => [m.member_id, m])), [members]);
  const a = child.parent_a ? byId[child.parent_a] : null;
  const b = child.parent_b ? byId[child.parent_b] : null;
  const benches = BENCHMARK_OPTIONS;

  const Beat = ({ k }) => {
    if (!a || !b) return null;
    const va = a.scores?.[k];
    const vb = b.scores?.[k];
    const vc = child.scores?.[k];
    if (typeof va !== 'number' || typeof vb !== 'number' || typeof vc !== 'number') return null;
    const beatBoth = vc > Math.max(va, vb);
    return beatBoth ? (
      <span title="Child beats both parents — emergent capability!" style={{ marginLeft: 6, color: '#d4a574', fontFamily: F.mono, fontSize: 10 }}>
        ★ emergent
      </span>
    ) : null;
  };

  return (
    <div style={{ background: C.bgI, border: `1px solid ${C.border}`, borderRadius: 8, padding: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
        <Sparkles size={12} color={C.acc} />
        <span style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
          Crossover inspector
        </span>
      </div>
      {!a || !b ? (
        <div style={{ fontFamily: F.ui, fontSize: 12, color: C.txtM }}>
          {child.member_id} is a seed (no parents).
        </div>
      ) : (
        <>
          <div style={{ fontFamily: F.mono, fontSize: 11, color: C.txtS, marginBottom: 8 }}>
            <span style={{ color: '#818cf8' }}>{a.member_id}</span>{' × '}
            <span style={{ color: '#fb923c' }}>{b.member_id}</span>{' '}
            <span style={{ color: C.txtM }}>α={typeof child.crossover_alpha === 'number' ? child.crossover_alpha.toFixed(2) : '—'}</span>
            {' · '}
            <span style={{ color: C.txtM }}>{child.crossover_strategy || '—'}</span>
          </div>
          <table style={{ width: '100%', fontFamily: F.mono, fontSize: 11, color: C.txtS, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ color: C.txtM }}>
                <th style={{ textAlign: 'left', padding: '4px 6px' }}>bench</th>
                <th style={{ textAlign: 'right', padding: '4px 6px', color: '#818cf8' }}>parent A</th>
                <th style={{ textAlign: 'right', padding: '4px 6px', color: '#fb923c' }}>parent B</th>
                <th style={{ textAlign: 'right', padding: '4px 6px', color: C.acc }}>child</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {benches.map((k) => (
                <tr key={k}>
                  <td style={{ padding: '3px 6px', color: BENCH_COLORS[k] }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                      {k}<InfoTooltip info={BENCHMARK_INFO[k]} size={11} />
                    </span>
                  </td>
                  <td style={{ textAlign: 'right', padding: '3px 6px' }}>{typeof a.scores?.[k] === 'number' ? a.scores[k].toFixed(3) : '—'}</td>
                  <td style={{ textAlign: 'right', padding: '3px 6px' }}>{typeof b.scores?.[k] === 'number' ? b.scores[k].toFixed(3) : '—'}</td>
                  <td style={{ textAlign: 'right', padding: '3px 6px' }}>{typeof child.scores?.[k] === 'number' ? child.scores[k].toFixed(3) : '—'}</td>
                  <td><Beat k={k} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

function LineageMiniTree({ members, selected, onSelect }) {
  // Group by generation, sort within by avg_score descending.
  const byGen = useMemo(() => {
    const m = new Map();
    for (const x of members) {
      const g = x.generation ?? 0;
      if (!m.has(g)) m.set(g, []);
      m.get(g).push(x);
    }
    for (const arr of m.values()) {
      arr.sort((a, b) => (b.avg_score || 0) - (a.avg_score || 0));
    }
    return m;
  }, [members]);
  const gens = Array.from(byGen.keys()).sort((a, b) => a - b);
  const rowH = 36;
  const colW = 130;
  const padX = 14;
  const padY = 14;
  const maxRows = Math.max(0, ...Array.from(byGen.values()).map((a) => a.length));
  const w = padX * 2 + Math.max(1, gens.length) * colW;
  const h = padY * 2 + Math.max(1, maxRows) * rowH;

  // Index for parent → child edges.
  const byId = Object.fromEntries(members.map((m) => [m.member_id, m]));
  const positions = {};
  for (const g of gens) {
    const arr = byGen.get(g);
    arr.forEach((m, i) => {
      positions[m.member_id] = {
        x: padX + (g - gens[0]) * colW + 50,
        y: padY + i * rowH + rowH / 2,
        m,
      };
    });
  }

  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid meet" style={{ background: '#06080d', borderRadius: 8 }}>
      {/* Edges first so nodes draw on top */}
      {members.map((m) => {
        if (!m.parent_a) return null;
        const child = positions[m.member_id];
        const pa = positions[m.parent_a];
        if (!child || !pa) return null;
        const tone = memberTone(m).fg;
        return (
          <line
            key={`e-${m.member_id}`}
            x1={pa.x + 14} y1={pa.y}
            x2={child.x - 14} y2={child.y}
            stroke={tone} strokeWidth={1.2} strokeDasharray="4 3" opacity={0.55}
          />
        );
      })}
      {gens.map((g, gi) => (
        <text
          key={`gh-${g}`}
          x={padX + gi * colW + 50}
          y={padY - 2}
          textAnchor="middle"
          fontSize={9}
          fontFamily="JetBrains Mono"
          fill="#94a3b8"
        >
          gen {g}
        </text>
      ))}
      {members.map((m) => {
        const p = positions[m.member_id];
        if (!p) return null;
        const tone = memberTone(m);
        const isSel = selected?.member_id === m.member_id;
        return (
          <g
            key={`n-${m.member_id}`}
            onClick={() => onSelect(m)}
            style={{ cursor: 'pointer' }}
          >
            <circle
              cx={p.x} cy={p.y} r={isSel ? 13 : 10}
              fill={tone.bg}
              stroke={tone.fg}
              strokeWidth={isSel ? 2 : 1.2}
              opacity={m.status === 'eliminated' ? 0.5 : 1}
            />
            <text
              x={p.x} y={p.y + 3}
              textAnchor="middle"
              fontSize={8}
              fontFamily="JetBrains Mono"
              fontWeight={600}
              fill={tone.fg}
            >
              {String(m.member_id).split('-').pop()}
            </text>
            {m.status === 'champion' ? (
              <text x={p.x} y={p.y - 14} textAnchor="middle" fontSize={10} fill="#d4a574">★</text>
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}

function EvolutionChart({ history }) {
  const data = useMemo(() => {
    return (history || []).map((snap) => {
      const alive = snap.population_alive || [];
      const scores = alive.map((m) => Number(m.avg_score) || 0);
      const champ = snap.champion?.avg_score || 0;
      return {
        generation: snap.generation,
        champion: champ,
        avg: scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0,
        max: scores.length ? Math.max(...scores) : 0,
        min: scores.length ? Math.min(...scores) : 0,
      };
    });
  }, [history]);
  if (!data.length) {
    return (
      <div style={{ fontFamily: F.ui, fontSize: 12, color: C.txtM, padding: 18 }}>
        Evolution chart will appear once the first generation completes.
      </div>
    );
  }
  return (
    <div style={{ height: 220 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 18, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={C.border} vertical={false} />
          <XAxis dataKey="generation" tick={{ fontSize: 10, fill: C.txtM }} />
          <YAxis tick={{ fontSize: 10, fill: C.txtM }} width={40} domain={[0, 1]} tickFormatter={(v) => v.toFixed(2)} />
          <Tooltip
            contentStyle={{ background: C.bgE, border: `1px solid ${C.borderL}`, borderRadius: 6, fontSize: 11 }}
          />
          <Line type="monotone" dataKey="champion" stroke="#d4a574" strokeWidth={2.4} dot={{ r: 3, fill: '#d4a574' }} />
          <Line type="monotone" dataKey="avg" stroke={C.acc} strokeWidth={1.6} dot={false} />
          <Line type="monotone" dataKey="max" stroke="#94a3b8" strokeWidth={1} strokeDasharray="3 3" dot={false} />
          <Line type="monotone" dataKey="min" stroke="#94a3b8" strokeWidth={1} strokeDasharray="3 3" dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function EPTPage() {
  const [status, setStatus] = useState(null);
  const [population, setPopulation] = useState(null);
  const [history, setHistory] = useState([]);
  const [events, setEvents] = useState([]);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState('');
  const [toast, setToast] = useState(null);

  // Control-panel form state
  const [form, setForm] = useState({
    population_size: 8,
    max_generations: 20,
    base_model: 'meta-llama/Llama-3.2-3B-Instruct',
    target_benchmarks: ['arc_challenge', 'hellaswag', 'mmlu'],
    eval_benchmarks: ['arc_challenge', 'hellaswag', 'mmlu', 'gsm8k'],
    mutation_steps: 50,
    mutation_lr: 1e-4,
    mutation_samples: 200,
    crossover_strategy: 'uniform',
    alpha_min: 0.3,
    alpha_max: 0.7,
    lora_rank: 16,
    lora_alpha: 32,
    batch_size: 2,
  });

  const showToast = (msg, tone = 'info') => {
    setToast({ msg, tone });
    setTimeout(() => setToast(null), 3000);
  };

  const loadAll = useCallback(async () => {
    try {
      const s = await apiFetch('/api/ept/status');
      setStatus(s);
      if (s?.run_id) {
        const [p, h, e] = await Promise.all([
          apiFetch('/api/ept/population').catch(() => null),
          apiFetch('/api/ept/history').catch(() => null),
          apiFetch('/api/ept/events?limit=120').catch(() => null),
        ]);
        if (p) setPopulation(p);
        if (h) setHistory(h.generations || []);
        if (e) setEvents(e.events || []);
      }
    } catch {
      /* leave previous state */
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);
  useEffect(() => {
    const iv = setInterval(loadAll, POLL_MS);
    return () => clearInterval(iv);
  }, [loadAll]);

  // Default-select the champion when population first loads.
  useEffect(() => {
    if (selected) return;
    const champ = population?.members?.find((m) => m.status === 'champion');
    if (champ) setSelected(champ);
  }, [population, selected]);

  async function startRun() {
    setBusy('start');
    try {
      const body = { ...form };
      const r = await apiFetch('/api/ept/start', { method: 'POST', body: JSON.stringify(body) });
      showToast(`Started EPT run ${r.run_id}`, 'success');
      await loadAll();
    } catch (e) {
      showToast(`Start failed: ${e?.body?.detail || e?.message}`, 'error');
    } finally {
      setBusy('');
    }
  }
  async function stopRun() {
    setBusy('stop');
    try {
      await apiFetch('/api/ept/stop', { method: 'POST' });
      showToast('Stop requested — current generation will finish first', 'info');
      await loadAll();
    } catch (e) {
      showToast(`Stop failed: ${e?.message}`, 'error');
    } finally {
      setBusy('');
    }
  }

  const isRunning = !!status?.is_running;
  const phase = status?.phase || 'idle';
  const champ = population?.members?.find((m) => m.status === 'champion');
  const members = useMemo(() => {
    const list = population?.members || [];
    return [...list].sort((a, b) => {
      const order = (m) => (m.status === 'champion' ? 0 : m.status === 'alive' ? 1 : 2);
      const o = order(a) - order(b);
      if (o !== 0) return o;
      if ((a.generation ?? 0) !== (b.generation ?? 0)) return (b.generation ?? 0) - (a.generation ?? 0);
      return (b.avg_score || 0) - (a.avg_score || 0);
    });
  }, [population]);

  if (status === null) {
    return <LoadingSkeleton rows={6} height={48} style={{ padding: '8px 0 40px', maxWidth: 1500, margin: '0 auto' }} />;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, padding: '8px 0 40px', maxWidth: 1500, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Dna size={22} color={C.acc} />
        <div style={{ flex: 1 }}>
          <h1 style={{ fontFamily: F.display, fontSize: 26, color: C.txtP, margin: 0 }}>Population Evolution (EPT)</h1>
          <p style={{ fontFamily: F.ui, fontSize: 13, color: C.txtM, margin: '4px 0 0' }}>
            Population-based LoRA adapter evolution: crossover · mutation · tournament selection · lineage tracking.
          </p>
        </div>
        <span style={{ fontFamily: F.mono, fontSize: 11, color: isRunning ? C.acc : C.txtM, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <span
            style={{
              width: 7, height: 7, borderRadius: 999,
              background: isRunning ? C.acc : C.txtM,
              boxShadow: isRunning ? `0 0 8px ${C.acc}` : 'none',
              animation: isRunning ? 'mf-topbar-pulse 1.4s ease-out infinite' : 'none',
            }}
            aria-hidden
          />
          {isRunning ? `LIVE · gen ${status?.generation || 0}/${status?.max_generations || '?'} · ${phase}` : 'idle'}
        </span>
      </div>

      {/* Control panel */}
      <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}>
          <Sparkles size={13} color={C.acc} />
          <span style={{ fontFamily: F.ui, fontSize: 13, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: C.txtM }}>
            Control panel
          </span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
          {/* Population size slider */}
          <Slider label="Population size" value={form.population_size} min={4} max={16} step={1}
            onChange={(v) => setForm((f) => ({ ...f, population_size: v, num_parents: Math.max(2, Math.floor(v / 2)) }))} />
          <Slider label="Max generations" value={form.max_generations} min={5} max={50} step={1}
            onChange={(v) => setForm((f) => ({ ...f, max_generations: v }))} />
          <Slider label="Mutation steps" value={form.mutation_steps} min={20} max={200} step={10}
            onChange={(v) => setForm((f) => ({ ...f, mutation_steps: v }))} />
          <Slider label="Mutation samples" value={form.mutation_samples} min={50} max={1000} step={50}
            onChange={(v) => setForm((f) => ({ ...f, mutation_samples: v }))} />
          <div>
            <Field label="Crossover strategy">
              <select
                value={form.crossover_strategy}
                onChange={(e) => setForm((f) => ({ ...f, crossover_strategy: e.target.value }))}
                style={selectStyle()}
              >
                {STRATEGY_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </Field>
          </div>
          <div>
            <Field label="Base model (HF id or Ollama tag)">
              <input
                value={form.base_model}
                onChange={(e) => setForm((f) => ({ ...f, base_model: e.target.value }))}
                style={inputStyle()}
              />
            </Field>
          </div>
        </div>

        <div style={{ marginTop: 12 }}>
          <Field label="Target benchmarks (curation focus)">
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {BENCHMARK_OPTIONS.map((b) => {
                const sel = form.target_benchmarks.includes(b);
                return (
                  <button
                    key={b}
                    type="button"
                    onClick={() => setForm((f) => ({
                      ...f,
                      target_benchmarks: sel
                        ? f.target_benchmarks.filter((x) => x !== b)
                        : [...f.target_benchmarks, b],
                    }))}
                    style={pillStyle(sel, BENCH_COLORS[b])}
                  >
                    {b}
                  </button>
                );
              })}
            </div>
          </Field>
        </div>

        <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
          <button
            type="button"
            onClick={startRun}
            disabled={isRunning || busy === 'start'}
            style={primaryBtn(isRunning || busy === 'start')}
          >
            <Play size={13} /> {busy === 'start' ? 'Starting…' : 'Start EPT'}
          </button>
          <button
            type="button"
            onClick={stopRun}
            disabled={!isRunning || busy === 'stop'}
            style={ghostBtn(!isRunning || busy === 'stop')}
          >
            <Pause size={13} /> Stop
          </button>
          <button
            type="button"
            onClick={loadAll}
            style={ghostBtn(false)}
          >
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      {/* Status strip */}
      {champ ? (
        <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 12, display: 'flex', flexWrap: 'wrap', gap: 18, alignItems: 'center', fontFamily: F.mono, fontSize: 11 }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#d4a574' }}>
            <Crown size={13} /> {champ.member_id}
          </span>
          <span><span style={{ color: C.txtM }}>avg</span> <span style={{ color: '#d4a574', fontSize: 14 }}>{(champ.avg_score || 0).toFixed(3)}</span></span>
          <span><span style={{ color: C.txtM }}>gen</span> <span style={{ color: C.txtP }}>{champ.generation}</span></span>
          {champ.parent_a && champ.parent_b ? (
            <span style={{ color: C.txtM }}>bred from {champ.parent_a} × {champ.parent_b} α={Number(champ.crossover_alpha || 0).toFixed(2)}</span>
          ) : null}
          <span style={{ marginLeft: 'auto', color: C.txtM }}>{members.length} total · {members.filter((m) => m.status !== 'eliminated').length} alive</span>
        </div>
      ) : null}

      {/* Body — population grid + lineage + chart */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 6fr) minmax(320px, 4fr)', gap: 14 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, minWidth: 0 }}>
          <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
              <span style={{ fontFamily: F.ui, fontSize: 12, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: C.txtM }}>
                Population
              </span>
              <span style={{ fontFamily: F.mono, fontSize: 10, color: C.txtM }}>{members.length} members</span>
            </div>
            {members.length === 0 ? (
              <div style={{ padding: 24, textAlign: 'center', fontFamily: F.ui, fontSize: 12, color: C.txtM }}>
                No population yet. Hit "Start EPT" to seed the initial generation.
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 8 }}>
                {members.map((m) => (
                  <MemberCard key={m.member_id} m={m} isSelected={selected?.member_id === m.member_id} onSelect={setSelected} />
                ))}
              </div>
            )}
          </div>
          <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
              <Zap size={12} color={C.acc} />
              <span style={{ fontFamily: F.ui, fontSize: 12, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: C.txtM }}>
                Evolution chart
              </span>
            </div>
            <EvolutionChart history={history} />
          </div>
          <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
              <GitBranch size={12} color={C.acc} />
              <span style={{ fontFamily: F.ui, fontSize: 12, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: C.txtM }}>
                Lineage
              </span>
              <span style={{ marginLeft: 'auto', fontFamily: F.mono, fontSize: 10, color: C.txtM }}>parent → child edges</span>
            </div>
            {members.length ? (
              <LineageMiniTree members={members} selected={selected} onSelect={setSelected} />
            ) : (
              <div style={{ padding: 24, textAlign: 'center', fontFamily: F.ui, fontSize: 12, color: C.txtM }}>
                Lineage tree will populate as generations land.
              </div>
            )}
          </div>
        </div>

        {/* Right pane: detail + crossover inspector + event log */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, minWidth: 280 }}>
          <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <span style={{ fontFamily: F.ui, fontSize: 12, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: C.txtM }}>
                Selected
              </span>
              {selected ? (
                <button type="button" onClick={() => setSelected(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: C.txtM }} title="clear">
                  <X size={13} />
                </button>
              ) : null}
            </div>
            {!selected ? (
              <div style={{ fontFamily: F.ui, fontSize: 12, color: C.txtM }}>Click a population card or a node in the lineage tree.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ padding: '2px 8px', borderRadius: 999, fontFamily: F.ui, fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', background: memberTone(selected).bg, color: memberTone(selected).fg, border: `1px solid ${memberTone(selected).border}` }}>
                    {memberTone(selected).label}
                  </span>
                  <span style={{ fontFamily: F.mono, fontSize: 12, color: C.txtP, fontWeight: 600 }}>{selected.member_id}</span>
                </div>
                <div style={{ fontFamily: F.mono, fontSize: 11, color: C.txtM }}>
                  generation {selected.generation} · created {fmtRel(selected.created_at)} · mut steps {selected.mutation_steps}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {BENCHMARK_OPTIONS.map((k) => {
                    const v = selected.scores?.[k];
                    return (
                      <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontFamily: F.mono, fontSize: 11 }}>
                        <span style={{ color: BENCH_COLORS[k], display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                          {k}<InfoTooltip info={BENCHMARK_INFO[k]} size={11} />
                        </span>
                        <span style={{ color: typeof v === 'number' ? C.txtP : C.txtM }}>
                          {typeof v === 'number' ? v.toFixed(3) : '—'}
                        </span>
                      </div>
                    );
                  })}
                </div>
                <CrossoverInspector child={selected} members={members} />
              </div>
            )}
          </div>

          {/* Event log */}
          <div style={{ background: C.bgC, border: `1px solid ${C.border}`, borderRadius: 8, padding: 0, display: 'flex', flexDirection: 'column' }}>
            <div style={{ padding: '10px 12px', borderBottom: `1px solid ${C.border}` }}>
              <span style={{ fontFamily: F.ui, fontSize: 12, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: C.txtM }}>
                Live events
              </span>
            </div>
            <div style={{ maxHeight: 280, overflowY: 'auto', padding: '4px 0' }}>
              {events.length === 0 ? (
                <div style={{ padding: 14, fontFamily: F.ui, fontSize: 12, color: C.txtM }}>
                  No events yet.
                </div>
              ) : (
                [...events].reverse().map((ev, i) => (
                  <div key={i} style={{ display: 'grid', gridTemplateColumns: '64px 1fr', gap: 8, padding: '4px 12px', fontFamily: F.mono, fontSize: 11, color: C.txtS, borderBottom: `1px solid rgba(30,41,59,0.5)` }}>
                    <span style={{ color: C.txtM }}>{fmtRel(ev.timestamp)}</span>
                    <span>
                      <span style={{ color: ev.level === 'warn' ? C.warning : C.acc, marginRight: 6 }}>{ev.phase}</span>
                      {ev.label}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      {toast ? (
        <div
          style={{
            position: 'fixed', bottom: 24, right: 24, padding: '10px 14px',
            background: toast.tone === 'error' ? `${C.danger}22` : toast.tone === 'success' ? `${C.acc}22` : C.bgC,
            border: `1px solid ${toast.tone === 'error' ? C.danger : toast.tone === 'success' ? C.acc : C.border}`,
            color: toast.tone === 'error' ? C.danger : toast.tone === 'success' ? C.acc : C.txtP,
            borderRadius: 6, fontFamily: F.ui, fontSize: 12, fontWeight: 600,
            zIndex: 200, animation: 'slide-up-fade 200ms ease-out',
          }}
        >
          {toast.msg}
        </div>
      ) : null}
    </div>
  );
}

// ── small UI primitives ─────────────────────────────────────────────────

function Field({ label, children }) {
  return (
    <label style={{ display: 'block' }}>
      <div style={{ fontFamily: F.mono, fontSize: 9, color: C.txtM, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 4 }}>
        {label}
      </div>
      {children}
    </label>
  );
}

function Slider({ label, value, min, max, step, onChange }) {
  return (
    <Field label={
      <span>{label} <span style={{ color: C.acc, marginLeft: 4 }}>{value}</span></span>
    }>
      <input
        type="range" min={min} max={max} step={step}
        value={value} onChange={(e) => onChange(Number(e.target.value))}
        style={{ width: '100%', accentColor: C.acc }}
      />
    </Field>
  );
}

function inputStyle() {
  return { width: '100%', background: C.bgI, border: `1px solid ${C.border}`, borderRadius: 6, color: C.txtP, padding: '6px 10px', fontFamily: F.mono, fontSize: 12 };
}
function selectStyle() {
  return { ...inputStyle(), padding: '7px 10px' };
}
function pillStyle(active, accent) {
  return {
    padding: '4px 10px', fontFamily: F.ui, fontSize: 11, fontWeight: 600,
    background: active ? `${accent}22` : 'transparent',
    border: `1px solid ${active ? accent : C.border}`,
    color: active ? accent : C.txtS,
    borderRadius: 999, cursor: 'pointer',
  };
}
function primaryBtn(disabled) {
  return {
    display: 'inline-flex', alignItems: 'center', gap: 6,
    padding: '8px 14px', fontFamily: F.ui, fontSize: 12, fontWeight: 600,
    background: disabled ? C.bgI : C.acc, color: disabled ? C.txtM : '#0a0e16',
    border: 'none', borderRadius: 6, cursor: disabled ? 'not-allowed' : 'pointer',
  };
}
function ghostBtn(disabled) {
  return {
    display: 'inline-flex', alignItems: 'center', gap: 6,
    padding: '8px 12px', fontFamily: F.ui, fontSize: 12,
    background: 'transparent', color: disabled ? C.txtM : C.txtS,
    border: `1px solid ${C.border}`, borderRadius: 6,
    cursor: disabled ? 'not-allowed' : 'pointer',
  };
}
