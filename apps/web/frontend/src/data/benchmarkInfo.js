// Static reference data for in-app tooltips. Update when new benchmarks
// are added to eval_backend.py / _TASK_CONFIG.
export const BENCHMARK_INFO = {
  mmlu: {
    name: 'MMLU',
    fullName: 'Massive Multitask Language Understanding',
    description:
      'Tests knowledge across 57 subjects including math, history, law, medicine. Like a college-level multiple-choice exam.',
    whatItMeasures: 'How much general knowledge the model has',
    goodScore: '60%+ is strong for 3B models, 80%+ is GPT-4 level',
    paperRef: 'Hendrycks et al., 2021',
    icon: '📚',
  },
  arc_challenge: {
    name: 'ARC-Challenge',
    fullName: 'AI2 Reasoning Challenge',
    description:
      'Grade-school science questions requiring reasoning, not just memorization. The "Challenge" set contains questions most models get wrong.',
    whatItMeasures: 'Scientific reasoning and common sense',
    goodScore: '50%+ for 3B models, 70%+ is excellent',
    paperRef: 'Clark et al., 2018',
    icon: '🔬',
  },
  hellaswag: {
    name: 'HellaSwag',
    fullName:
      'Harder Endings, Longer contexts, and Low-shot Activities for Situations With Adversarial Generations',
    description:
      'Given a scenario, pick the most logical continuation. Tests whether the model understands everyday situations and activities.',
    whatItMeasures: 'Common sense reasoning and situation understanding',
    goodScore: '70%+ for 3B models, 90%+ is excellent',
    paperRef: 'Zellers et al., 2019',
    icon: '🧠',
  },
  gsm8k: {
    name: 'GSM8K',
    fullName: 'Grade School Math 8K',
    description:
      '8,500 grade-school math word problems requiring 2–8 step reasoning. The model must show its work and arrive at the correct numerical answer.',
    whatItMeasures: 'Mathematical reasoning and step-by-step problem solving',
    goodScore: '40%+ for 3B models, 80%+ is strong',
    paperRef: 'Cobbe et al., 2021',
    icon: '🔢',
  },
  humaneval: {
    name: 'HumanEval',
    fullName: 'HumanEval Code Generation',
    description:
      '164 Python programming problems. The model writes a function, then automated tests check whether the code actually runs correctly.',
    whatItMeasures: 'Code generation ability — can the model write working Python?',
    goodScore: '25%+ for 3B models, 50%+ is strong',
    paperRef: 'Chen et al., 2021 (OpenAI Codex paper)',
    icon: '💻',
  },
  humaneval_plus: {
    name: 'HumanEval+',
    fullName: 'HumanEval Plus (EvalPlus)',
    description:
      'Extended version with 80× more test cases per problem. Catches models that pass basic tests but fail edge cases. More rigorous than standard HumanEval.',
    whatItMeasures: 'Robust code generation — does the code handle edge cases?',
    goodScore: '20%+ for 3B models, 45%+ is strong',
    paperRef: 'Liu et al., 2023 (EvalPlus)',
    icon: '💻+',
  },
};

export const CONCEPT_INFO = {
  lora: {
    name: 'LoRA',
    fullName: 'Low-Rank Adaptation',
    description:
      'A technique to fine-tune large models by training only a small set of additional parameters (typically 0.1–2% of the model). Much faster and cheaper than full fine-tuning.',
    analogy: 'Like adding a small plugin to a big engine instead of rebuilding the engine.',
  },
  lora_rank: {
    name: 'LoRA Rank',
    description:
      'Controls how many parameters LoRA adds. Higher rank = more capacity to learn but slower training and more memory. Rank 8–16 is typical.',
    range: '4 (minimal) → 64 (maximum capacity)',
    default: 16,
  },
  lora_alpha: {
    name: 'LoRA Alpha',
    description:
      'Scaling factor for LoRA updates. Usually set to 2× the rank. Controls how strongly the adapter modifies the base model.',
    default: 32,
  },
  learning_rate: {
    name: 'Learning Rate',
    description:
      'How fast the model learns from training data. Too high = unstable, forgets what it knew. Too low = barely learns anything.',
    range: '1e-5 (very cautious) → 5e-4 (aggressive)',
    default: '2e-4',
  },
  pareto: {
    name: 'Pareto Selection',
    description:
      'A child model is promoted only if it improves on at least one benchmark WITHOUT getting significantly worse on any other. Prevents the "good at math but forgot English" problem.',
  },
  ept: {
    name: 'EPT (Evolutionary Population Training)',
    description:
      'Instead of evolving one model at a time, maintain a population of models. Breed the best ones together (crossover) and mutate the children. Like natural selection for AI models.',
  },
  crossover: {
    name: 'Weight Crossover',
    description:
      'Take two trained adapters and blend their weights to create a child. The child may inherit strengths from both parents — like genetic crossover in biology.',
    strategies: {
      uniform: 'Simple weighted average of all parameters',
      ties: 'Trim small changes, vote on direction, then merge (NeurIPS 2023)',
      dare: 'Randomly drop some changes, rescale the rest, then merge (Yu et al. 2024)',
      layer_wise: 'Different blend ratios for different layers of the model',
    },
  },
  champion: {
    name: 'Champion',
    description:
      'The current best-performing adapted model. New children must beat the champion to take its place. If they cannot, they are discarded.',
  },
  generation: {
    name: 'Generation',
    description:
      'One cycle of: identify weaknesses → gather training data → train → evaluate → promote or discard. Like one generation in biological evolution.',
  },
};
