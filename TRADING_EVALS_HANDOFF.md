# Trading-Evals Handoff

**Branch:** `feat/trading-evals` (off `main`)
**Scope:** Additive only. No existing module touched in a way that changes
behavior for non-trading runs.

This pack adds trading-specific scoring modules under
`apps/api/src/agents/evals/`. They implement the existing `EvalBackend`
protocol contract (return an `EvalResult` whose `scores` is a free-form
`dict[str, float]`) so the Pareto-promotion machinery in
`evolution_graph.py` consumes them with zero changes.

The trading-bot repo's `docs/MODELFORGE_INTEGRATION_PLAN.md` is the
governing spec; this is the model-forge side of that integration.

---

## What each eval measures and why it matters for trading

### `eval_reflector` (track: `trading-reflector`)
The Reflector writes 2-4 sentence post-mortems for closed paper trades.
Four metrics score whether those post-mortems are factually grounded
(`faithfulness_regex` — cites the realized P&L to one decimal place),
well-judged (`judge_score` — prior-adapter LLM-as-judge on a clarity +
causal-reasoning rubric, rescaled to [0, 1]), decision-relevant
(`debate_impact` — A/B feeds the reflection into the trading-arbiter and
measures decision-change rate, capped so a stochastic adapter can't farm
the score), and predictive (`predictive_hit_rate_30d` — forward-window
hit-rate against the held-out trade's realized 30-day return).
`predictive_hit_rate_30d` is the **Pareto tiebreaker** for this track:
when it regresses >5% vs parent the candidate is flagged for rollback
regardless of other scores. This is operator's locked decision #3.

### `eval_debater` (tracks: `trading-bull` AND `trading-bear`)
Both sides of the pre-market debate produce prose arguments. Same metric
shape for each. `evidence_density` counts dollar-prices, percent-moves,
ISO dates, and indicator names per 100 tokens — a debater that asserts
without numbers is hand-waving. Normalized against a 3-evidence-per-100
target calibrated against top-quartile training samples.
`opponent_acknowledgment_rate` checks that the response names a non-trivial
subtoken of the opposing side's strongest point (trading-bot's debate
format penalises one-sided dismissal). `judge_preference` is pairwise win
rate against the prior adapter. Same module serves bull and bear via the
`role` argument — the registry wraps them with `functools.partial`.

### `eval_arbiter` (track: `trading-arbiter`)
The Portfolio Manager role; the most consequential. Three metrics:
`structured_output_validity_rate` (parses as `TraderProposal` — below 0.9
means the role is broken for production), `decision_consistency` (re-run
the same prompt N=3 times at temperature=0 and check action+ticker+horizon
are identical — catches silent regressions where the adapter starts
hallucinating different tickers on identical evidence), and
`downstream_pnl_per_decision` (sigmoid-squashed realized 5-day P&L of the
recommended action, $0=0.5, ±$500=±0.23 from neutral). Arbiter is the
strictest track — Pareto tiebreaker threshold is **3%** instead of the
default 5%.

### `eval_structured_json` (tracks: `trading-regime-tagger` AND `trading-indicator-selector`)
Shared scorer for the two JSON-output roles. `structured_output_validity_rate`
parses against the supplied Pydantic schema. `agreement_with_baseline`
compares the parsed output against the test set's baseline classifier
(an HMM for regime, a hardcoded ranking for indicators). For regimes
that's strict label equality; for indicators it's Jaccard ≥ 0.5 (strict
equality is too harsh; 0.5 overlap at least agrees on the strategy
family).

---

## Pareto tiebreaker rule — *predictive hit-rate wins*

Per the trading-bot operator's locked decision #3, certain metrics carry
veto power for their track. The mapping lives in
`apps/api/src/config/trading_eval_weights.py`:

| Track | Tiebreaker metric | Rollback threshold |
|---|---|---|
| `trading-reflector` | `predictive_hit_rate_30d` | 5% |
| `trading-bull` | `judge_preference` | 5% |
| `trading-bear` | `judge_preference` | 5% |
| `trading-arbiter` | `downstream_pnl_per_decision` | **3%** (tighter) |
| `trading-regime-tagger` | `agreement_with_baseline` | 5% |
| `trading-indicator-selector` | `agreement_with_baseline` | 5% |

When the priority metric regresses by more than the threshold vs parent,
the candidate is **discarded regardless of Pareto outcome**. The check
runs inside `evolution_graph.compare_to_champion` only when
`config["track_id"]` starts with `trading-`; standard MMLU/GSM8K runs are
untouched. The veto event is also published to the `run_events` bus so
the dashboard's events panel surfaces it.

Edge cases:
- **Parent ~ 0**: switches to absolute delta against threshold so a
  metric stuck at zero doesn't divide-by-zero.
- **Metric missing from either side**: no veto. First generation gets a
  free pass; metrics added mid-stream don't break in-flight runs.
- **Tiebreaker dispatch error**: logged, ignored, run continues. Pareto +
  regression guards still apply.

---

## CLI: run one eval module for one-off testing

Each module exposes a `score(adapter_path, test_set_path, **kwargs)` function
returning an `EvalResult`. The registry wraps role/schema specialisation
with `functools.partial`. From a Python REPL inside the container or
host venv with `apps/api/src` on `sys.path`:

```python
# Direct module call
from agents.evals import eval_reflector
result = eval_reflector.score(
    adapter_path="/srv/modelforge-data/adapters/run-XXXX/gen-3",
    test_set_path="/srv/modelforge-data/curated/trading-reflector/gen-3/test.jsonl",
)
print(result.scores)

# Registry dispatch by track_id
from agents.evals.eval_registry import run_for_track
result = run_for_track(
    "trading-arbiter",
    "/srv/modelforge-data/adapters/run-YYYY/gen-1",
    "/srv/modelforge-data/curated/trading-arbiter/gen-1/test.jsonl",
    consistency_n=3,
)
print(result.scores)
```

For end-to-end runs through the evolution graph, set the
`POST /api/evolve/start` body with the trading fields (this requires the
matching `EvolutionRequest` schema additions from Day 2 of the integration
plan — already separately tracked):

```bash
curl -X POST http://localhost:8000/api/evolve/start \
  -H "X-API-Key: $MODELFORGE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "track_id": "trading-reflector",
    "base_model": "Qwen/Qwen2.5-32B-Instruct",
    "curated_path": "/srv/modelforge-data/curated/trading-reflector/gen-1",
    "eval_set_path": "/srv/modelforge-data/curated/trading-reflector/gen-1/test.jsonl",
    "max_generations": 1
  }'
```

The runner's `_select_backends` will need a one-line update to wrap
`LMEvalHarnessBackend()` in `TradingEvalBackend(fallback=...)` when the
trading track package is installed; that wiring is intentionally left to
the Day-2 integration commit so this branch stays additive-only.

---

## Test command

```bash
# All trading-eval tests (27 cases, ~0.1s on Mac dev)
python -m pytest apps/api/tests/test_trading_evals.py -v

# Smoke check that the existing suite still passes (excluding known
# pre-existing failures in test_campaign_runner / test_crossover —
# those fail on main without this branch).
python -m pytest apps/api/tests/ \
  --deselect apps/api/tests/test_campaign_runner.py::test_eval_only_experiment_uses_eval_backend \
  --deselect apps/api/tests/test_crossover.py::test_crossover_rejects_incompatible_parents \
  -q
```

The trading-eval tests run without torch / peft / GPU. The adapter
runner, judge, and rubric scorer are all injectable callable defaults so
tests pass stub functions; production wires the real PEFT inference path
behind `MODELFORGE_EVAL_USE_PEFT=1`.

---

## Schema duplication caveat + future fix path

`apps/api/src/agents/evals/trading_schemas.py` duplicates three Pydantic
models from trading-bot:

- `TraderProposal` (arbiter output)
- `RegimeTag` (regime-tagger output)
- `IndicatorSelection` (indicator-selector output)

These are the authoritative shapes the trading-bot LLM roles produce. The
canonical copies live in trading-bot under `stocks/memory/` /
`stocks/shark/llm/schemas/`. Keeping a separate copy in model-forge means
the trading-bot exporter can change a schema and silently desync from
the eval validator — bad.

**Why duplicate today.** Cross-repo schema sharing requires either (a) a
git submodule, (b) a published Python package, or (c) a build-time
codegen. All three are heavier than the integration plan's day-1 budget
allows. ModelForge needs to be importable without trading-bot installed
(the "no trading-bot import at runtime" invariant).

**Future cleanup**. Extract these three classes — plus
`RegimeLabel`, `_KNOWN_INDICATORS` — into a tiny `trading-protocols`
package (a 50-line `pyproject.toml` + one Python file), publish to a
private PyPI or pin via git+https, and depend on it from both repos. The
package would carry a single schema version field so both sides can
detect drift at startup.

Until that lands, **the rule is**: every time a trading-bot schema
changes, update `trading_schemas.py` here in the same PR. Add a CHANGELOG
entry at the top of this file noting the bump.

---

## Files added on this branch

```
apps/api/src/agents/evals/
├── __init__.py
├── _common.py                 # shared helpers: test-set loader, evidence regex, sigmoid
├── eval_arbiter.py            # trading-arbiter scoring
├── eval_debater.py            # trading-bull + trading-bear scoring (role= arg)
├── eval_reflector.py          # trading-reflector scoring
├── eval_registry.py           # track_id -> scorer dispatch
├── eval_structured_json.py    # trading-regime-tagger + trading-indicator-selector scoring
└── trading_schemas.py         # duplicated Pydantic schemas (see caveat above)

apps/api/src/config/trading_eval_weights.py
                               # Pareto tiebreaker config (priority metric per track)

apps/api/tests/test_trading_evals.py
                               # 27 test cases covering modules, registry, tiebreaker, schemas

TRADING_EVALS_HANDOFF.md       # this document
```

## Files modified on this branch

```
apps/api/src/agents/eval_backend.py
  + class TradingEvalBackend (additive: legacy backends untouched)

apps/api/src/agents/evolution_graph.py
  + trading_tiebreaker_report field in EvolutionState
  + tiebreaker veto block inside compare_to_champion (guarded by
    track_id.startswith("trading-") so it never fires on standard runs)
```

Total: ~1100 LOC including tests + this handoff.
