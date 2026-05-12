# Trading Track-ID Pipeline — Handoff

**Branch:** `feat/track-id-pipeline` (off `main`, NOT pushed)
**Task:** #46 path A — wire `track_id` through `evolution.start` → runner → eval backend so trading-* tracks actually score against their custom evals (and therefore promote).

## Why this matters

Before this change, the workflow action `evolution.start` had **no `track_id` field** in its schema. Even if a config dict somehow carried one, the runner's `_select_backends()` returned a raw `LMEvalHarnessBackend` that never inspects `track_id` — so trading tracks always fell through to MMLU/ARC/HellaSwag. Every "Trading Tracks Weekly Champion" run silently re-ran the legacy benches and the trading-reflector / debater / arbiter scorers were dead code in production.

## The 3-stop plumbing path (after the fix)

1. **Action layer — `EvolutionStart.execute()`** (`apps/api/src/services/automation_engine/actions.py`)
   - Schema now exposes `{"name": "track_id", "type": "string", "default": ""}` so the workflow UI / API can set it.
   - Empty-string `track_id` is stripped from `run_config` (legacy shape preserved); non-empty value flows through to `start_evolution(run_id, run_config, db)`.

2. **Runner state — `_run()`** (`apps/api/src/agents/runner.py`)
   - Reads `config.get("track_id")`, stamps `state["track_id"]` on the langgraph `EvolutionState`.
   - `_select_backends()` now wraps the chosen eval backend in `TradingEvalBackend(fallback=...)` for **both** the mock-dev and GPU-prod paths. The fallback (`MockEvalBackend` or `LMEvalHarnessBackend`) handles non-trading runs unchanged — additive-only.
   - Logs `[evolution <id>] track_id=trading-reflector — per-track eval dispatch enabled` on entry when set.

3. **Eval invocation — `evolution_graph.evaluate` node** (`apps/api/src/agents/evolution_graph.py`)
   - Builds `eval_config = dict(state["config"])`, then re-injects `state["track_id"]` (belt-and-suspenders so a stale config dict can never drop the routing key).
   - Calls `eval_backend.evaluate(..., config=eval_config)`. `TradingEvalBackend` reads `config["track_id"]`, looks it up in `eval_registry.EVAL_REGISTRY`, and dispatches to the per-track scorer. Missing/unknown track_id → falls through to the wrapped legacy backend.

Total LOC delta:

```
 apps/api/src/agents/evolution_graph.py             | 16 ++++++++++-
 apps/api/src/agents/runner.py                      | 32 ++++++++++++++++++++--
 apps/api/src/services/automation_engine/actions.py | 13 +++++++++
 3 files changed, 57 insertions(+), 4 deletions(-)
```

Plus a new test file (`apps/api/tests/test_track_id_pipeline.py`, 10 tests) — see below.

## Sample workflow config that now works

The existing "Trading Tracks Weekly Champion" workflow at
`/api/automation/workflows/c1f9eb2d-7089-477f-96c2-a850fab41fb2` only needs the
`config.track_id` field added to its `evolution.start` action:

```json
{
  "type": "evolution.start",
  "config": {
    "base_model": "meta-llama/Llama-3.2-3B-Instruct",
    "max_generations": 2,
    "max_samples": 1000,
    "lora_rank": 16,
    "batch_size": 2,
    "learning_rate": 0.0002,
    "track_id": "trading-reflector",
    "eval_set_path": "/data/trading-evals/reflector_eval_set.jsonl"
  }
}
```

`eval_set_path` is still required by `TradingEvalBackend` so the scorer knows
which JSONL to score against — that's unchanged from `TRADING_EVALS_HANDOFF.md`.

## Why 1 workflow with `track_id` beats 6 workflows for now

The natural alternative — split the existing weekly workflow into 6 (one per
track) — was rejected. Reasons:

- The existing per-run track promotion loop
  (`runner._maybe_promote_to_tracks → db.list_tracks`) already iterates every
  enabled track and promotes the adapter into any track whose
  `target_benchmarks` it beats. One run, six independent promotion decisions.
- The `TradingEvalBackend` scorer returns a `scores` dict with multiple keys
  (`coverage`, `grounded_evidence`, `faithfulness_regex`, etc.) — the
  promotion loop picks the right subset per track via `_avg_subset()`.
- Splitting into 6 workflows means 6x the GPU time and 6x the cron noise for
  the same outcome.
- The day a track grows divergent base-model / hyperparameter needs, splitting
  becomes obvious — but until then a single `track_id: trading-reflector` run
  produces scores that all six tracks' promotion loops can score against.

## Test command + result

Run from the `apps/api/` dir:

```bash
python -m pytest tests/test_track_id_pipeline.py -v
python -m pytest tests/test_trading_evals.py -v          # baseline 27
python -m pytest tests/test_training_backend_curated.py -v  # baseline 11 (OpenOrca fix)
```

Results on `feat/track-id-pipeline`:

| Suite | Pass | Notes |
|---|---|---|
| `test_track_id_pipeline.py` | **10/10** | New — covers all 4 hops |
| `test_trading_evals.py` | **27/27** | Baseline unchanged |
| `test_training_backend_curated.py` | **11/11** | OpenOrca fix unchanged |
| Full `apps/api/tests/` minus 4 pre-existing main failures | **115/115** | No new regressions |

The 4 pre-existing failures (`test_campaigns::*`, `test_campaign_runner::test_eval_only_experiment_uses_eval_backend`, `test_crossover::test_crossover_rejects_incompatible_parents`) reproduce on `main` without this branch — they touch auth middleware / eval-worker subprocess / LoRA crossover, none of which this PR modifies. Filed separately, not blockers.

## Operator merge + restart commands

```bash
# Review
cd /home/saijayanthai/Documents/spark/workspace/model-forge
git diff main..feat/track-id-pipeline

# Merge (squash or merge-commit, your call)
git checkout main
git merge --no-ff feat/track-id-pipeline -m "feat: wire track_id from evolution.start through runner into eval backend"

# Rebuild and restart api container
docker compose build api && docker compose up -d api
docker logs --tail 50 mf-api  # confirm clean boot

# Update the weekly workflow to add track_id
# Either via dashboard at /forge/automation, or via API:
curl -X PUT http://localhost:8000/api/automation/workflows/c1f9eb2d-7089-477f-96c2-a850fab41fb2 \
  -H "Authorization: Bearer $MODELFORGE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "actions": [{
          "type": "evolution.start",
          "config": {
            "track_id": "trading-reflector",
            "eval_set_path": "/data/trading-evals/reflector_eval_set.jsonl",
            "base_model": "meta-llama/Llama-3.2-3B-Instruct",
            "max_generations": 2,
            "max_samples": 1000,
            "lora_rank": 16,
            "batch_size": 2,
            "learning_rate": 0.0002
          }
        }],
        "enabled": true
      }'
```

Enable the workflow last (`enabled: true`) so the next cron tick fires the
correctly-wired evolution run.

## Verification on the next run

After the workflow fires, look for these signals in `docker logs mf-api`:

```
[evolution run-xxxxxxxx] track_id=trading-reflector — per-track eval dispatch enabled
[trading-eval trading-reflector] run=run-xxxxxxxx gen=1 scores={'coverage': 0.83, 'grounded_evidence': 0.71, ...} (...)
[track] trading-reflector now owned by run-xxxxxxxx::gen1 — avg over [...]: 0.7XXX
```

If you see `[trading-eval]` and `[track] ... now owned by` lines, the path is
hot. If you see the legacy lm-eval-harness sweep (MMLU/ARC/HellaSwag), the
config didn't carry `track_id` — recheck the workflow's `config` dict.

---

Branch is local only. Operator merges + ships.
