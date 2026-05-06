"""EPT — Evolutionary Population Training of LoRA adapters.

What's here
-----------
* crossover.py   — weight-space breeding of two PEFT adapters (3 strategies)
* mutation.py    — short LoRA fine-tune that perturbs an existing adapter
* population.py  — population manager (selection / crossover / mutation /
                   survival / lineage tracking)
* runner.py      — orchestrator that runs N generations end-to-end

Honest scoping note (engineer-to-engineer)
-----------------------------------------
The crossover-style merging of LoRA weight matrices is *not* a brand-new
mathematical idea — model merging (TIES, DARE, Model Soups, LoRA Hub) is an
active research area. What this package does that's worth shipping:

1. Wraps the merge into a reusable operator inside an autonomous evolution
   loop with tournament selection and per-member lineage tracking.
2. Persists the full provenance (parent_a, parent_b, alpha, strategy) so the
   resulting champion is reproducible from a single record.
3. Pairs with the existing dashboard/automation infrastructure so a
   non-research user can drive it without touching a notebook.

Heavy compute (PEFT, transformers, lm-eval) is lazy-imported per call so
loading this package has zero cost on API boot.
"""

from .crossover import crossover, CrossoverStrategy           # noqa: F401
from .mutation import mutate_adapter                          # noqa: F401
from .population import (                                     # noqa: F401
    PopulationConfig,
    PopulationManager,
    PopulationMember,
)
from .runner import EPTRunner, get_runner                     # noqa: F401

__all__ = [
    "crossover",
    "CrossoverStrategy",
    "mutate_adapter",
    "PopulationConfig",
    "PopulationManager",
    "PopulationMember",
    "EPTRunner",
    "get_runner",
]
