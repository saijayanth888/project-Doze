function mulberry32(seed) {
  return function () {
    seed |= 0; seed = seed + 0x6D2B79F5 | 0;
    let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}

const WEAK_POOL = [
  'Low GSM8K accuracy on multi-step problems',
  'HumanEval struggles with recursion',
  'ARC fails on spatial reasoning',
  'HellaSwag context window degradation',
  'MMLU physics subset underperformance',
  'Code generation misses edge cases',
  'Math word problem parsing errors',
];

const REASONS = [
  'Exceeded parent on all benchmarks',
  'Marginal improvement — promoted for diversity',
  'Strong code generation breakthrough',
  'MMLU and ARC improvements justify promotion',
  'HellaSwag plateau — discarded',
  'Score regression on GSM8K — discarded',
  'Instability on long-context — discarded',
  'Dominant across 4 of 5 benchmarks',
  'HumanEval breakthrough +8.2%',
  'Failed to converge — discarded',
];

const METHODS = [
  'Evolutionary Score Distillation™',
  'Adversarial Benchmark Probing™',
  'Lineage-Aware Gradient Shaping™',
  'Champion Retention Protocol™',
  'Score-Weighted Mutation™',
];

export function buildGens(n = 25) {
  const rng = mulberry32(42);
  const scores = { mmlu: 0.634, arc_challenge: 0.582, hellaswag: 0.612, gsm8k: 0.471, humaneval: 0.354 };
  const gens = [];

  const phases = [
    { range: [1, 5],   delta: [0.002, 0.012], discardRate: 0.40 },
    { range: [6, 15],  delta: [0.005, 0.020], discardRate: 0.30 },
    { range: [16, 20], delta: [-0.003, 0.008], discardRate: 0.60 },
    { range: [21, 25], delta: [0.010, 0.035], discardRate: 0.20 },
  ];

  for (let i = 1; i <= n; i++) {
    const phase = phases.find(p => i >= p.range[0] && i <= p.range[1]);
    const [lo, hi] = phase.delta;
    const promoted = rng() > phase.discardRate;

    const parentScores = { ...scores };
    const childScores = {};

    for (const k of Object.keys(scores)) {
      const delta = lo + rng() * (hi - lo);
      const noise = (rng() - 0.5) * 0.01;
      childScores[k] = Math.min(0.99, Math.max(0.30, scores[k] + delta + noise));
    }

    if (promoted) {
      for (const k of Object.keys(scores)) scores[k] = childScores[k];
    }

    const weakIdx = Math.floor(rng() * WEAK_POOL.length);
    const reasonIdx = Math.floor(rng() * REASONS.length);
    const methodIdx = Math.floor(rng() * METHODS.length);

    const baseDate = new Date('2025-01-01T00:00:00Z');
    baseDate.setDate(baseDate.getDate() + (i - 1) * 3 + Math.floor(rng() * 2));

    gens.push({
      generation: i,
      promoted,
      parentScores,
      childScores,
      weakCategories: [WEAK_POOL[weakIdx], WEAK_POOL[(weakIdx + 1) % WEAK_POOL.length]],
      decisionReason: REASONS[reasonIdx],
      method: METHODS[methodIdx],
      trainingDataSize: Math.floor(50000 + rng() * 150000),
      timestamp: baseDate.toISOString(),
      duration: Math.floor(120 + rng() * 480),
      gpuUtil: Math.floor(70 + rng() * 28),
      mutationRate: parseFloat((0.02 + rng() * 0.08).toFixed(3)),
    });
  }
  return gens;
}

export const GENS = buildGens(25);

export const CHAMPION = GENS.filter(g => g.promoted).reduce((best, g) =>
  g.childScores.mmlu > (best?.childScores?.mmlu ?? 0) ? g : best, null
);

export const TICKER_ITEMS = [
  { label: 'GEN 25', value: 'ACTIVE', color: '#76b900' },
  { label: 'MMLU', value: (CHAMPION?.childScores?.mmlu * 100).toFixed(1) + '%', color: '#818cf8' },
  { label: 'HUMANEVAL', value: (CHAMPION?.childScores?.humaneval * 100).toFixed(1) + '%', color: '#f472b6' },
  { label: 'GSM8K', value: (CHAMPION?.childScores?.gsm8k * 100).toFixed(1) + '%', color: '#fbbf24' },
  { label: 'GENERATIONS', value: '25', color: '#c084fc' },
  { label: 'PROMOTED', value: GENS.filter(g => g.promoted).length + '', color: '#76b900' },
  { label: 'STATUS', value: 'TRAINING', color: '#818cf8' },
  { label: 'METHOD', value: 'ESD™', color: '#d4a574' },
];

export const BENCHMARK_LABELS = {
  mmlu: 'MMLU',
  arc_challenge: 'ARC-C',
  hellaswag: 'HellaSwag',
  gsm8k: 'GSM8K',
  humaneval: 'HumanEval',
};

export const NAV = [
  { key: 'dashboard', label: 'Dashboard', icon: 'LayoutDashboard', path: '/dashboard' },
  { key: 'lineage',   label: 'Lineage',   icon: 'GitBranch',      path: '/lineage' },
  { key: 'benchmarks',label: 'Benchmarks',icon: 'BarChart3',      path: '/benchmarks' },
  { key: 'playground',label: 'Playground',icon: 'Terminal',       path: '/playground' },
  { key: 'settings',  label: 'Settings',  icon: 'Settings',       path: '/settings' },
];
