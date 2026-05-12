# Handoff — `fix/honor-curated-path`

Branch: `fix/honor-curated-path` (off `stage/license-mit-modelforge`, 2026-05-12).
Owner-only — no remote push.

## What changed

| File                                              | Change                                                                                                                                                                                       |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/api/src/agents/training_backend.py`         | New helper `_resolve_curated_path()` (lines 25-65). Inside `_train_sync_inner`, replaced the hardcoded `load_dataset("Open-Orca/OpenOrca", ...)` with a branch that prefers `load_from_disk(curated_path)` and falls back to OpenOrca with a `WARNING` log (lines ~325-349). Added `load_from_disk` to the lazy `datasets` import. |
| `apps/api/src/agents/evolution_graph.py`          | `train_adapter` now injects `state["training_data_path"]` into `config["curated_path"]` before calling `training.train(...)` (lines ~525-543). Without this, the trainer's new branching logic would never see the curated path because the graph never propagated it. |
| `apps/api/tests/test_training_backend_curated.py` | New — 11 tests covering the path-resolver, the dataset-loading branch, and the graph's config-injection. |

## Why it matters

`trading-bot/docs/MODELFORGE_INTEGRATION_PLAN.md` documents this as **issue R1** — "The trainer currently bypasses curated data entirely and hardcodes Open-Orca/OpenOrca (`training_backend.py:301`). **This is the single biggest blocker**." Every previous LoRA fine-tune in this codebase trained on OpenOrca, regardless of how many CPU-hours `data_curator` and the Ollama self-augmentation step spent producing weakness-targeted training data. The curation pipeline was effectively a no-op.

After this fix:

- `data_curator.curate(...)` writes the Arrow shard to `<MODELFORGE_DATA_ROOT>/curated/gen-<N>/`.
- `augment_training` appends self-distilled samples to the same shard.
- `train_adapter` injects that path into `config["curated_path"]`.
- The LoRA backend calls `load_from_disk(<curated_path>)` (validated to be under the configured data root) and trains on the actual curated dataset.
- OpenOrca remains as a cold-start fallback for runs that legitimately have no curated data, emitted with a `WARNING` so the regression is visible in logs.

## Call-chain proof — `curated_path` reaches the trainer

```
data_curator.HuggingFaceCurator.curate()
  └─ writes to: settings.resolve_data_root() / "curated" / f"gen-{generation}"
  └─ returns: CurationResult(data_path=<that path>, ...)

evolution_graph.generate_training (node)
  └─ state["training_data_path"] = result.data_path                  # already existed

evolution_graph.augment_training (node)
  └─ load_from_disk(path) + Dataset.from_list(merged).save_to_disk(path)  # already existed
     # path is the same state["training_data_path"]; samples are appended in place.

evolution_graph.train_adapter (node)              # NEW PROPAGATION ADDED HERE
  └─ train_config = dict(cfg)
  └─ train_config["curated_path"] = state["training_data_path"]      # NEW
  └─ await training.train(run_id=..., generation=..., config=train_config)

training_backend.LoRATrainingBackend.train()
  └─ _run_train_subprocess(run_id, generation, config)               # serializes config to JSON
     └─ spawn: python train_worker.py --config '<json>'
        └─ train_worker.main() reads --config back into a dict
        └─ LoRATrainingBackend()._train_sync_inner(run_id, generation, config)
           └─ curated_path = config.get("curated_path") or config.get("training_data_path")   # NEW
           └─ safe = _resolve_curated_path(curated_path)              # NEW — guards data root
           └─ raw = load_from_disk(str(safe))    if safe else  load_dataset("Open-Orca/OpenOrca", ...)
           └─ logger.info / logger.warning depending on which branch fired
```

The unit test `test_evolution_graph_injects_curated_path_into_trainer_config` exercises every hop above using mock backends — see `apps/api/tests/test_training_backend_curated.py::test_evolution_graph_injects_curated_path_into_trainer_config`.

## Security — path traversal guard

`_resolve_curated_path` only accepts paths that, **after symlink resolution**, sit under `settings.resolve_data_root()`. Specifically:

- `curated_path="../../etc"` → rejected with `WARNING [curated-path] rejected ... — not under configured data root ...`
- `curated_path="/etc/passwd"` → rejected (same warning).
- `curated_path="<data_root>/curated/gen-3"` → accepted.
- `curated_path=""` or `None` → silent, falls through to OpenOrca with a "no curated_path provided" warning (cold-start path).

The reject-and-fall-back design (versus reject-and-raise) keeps the trainer resilient to bad upstream config while making the regression loud in logs — matching the project's "fail-soft on operator config, fail-loud in logs" pattern already used in `_train_sync_inner`'s memory guard.

## Test command + result

```
cd apps/api && /home/saijayanthai/Documents/spark/workspace/model-forge/.venv/bin/pytest tests -q
```

Last run on this branch:

```
78 passed, 4 failed in 8.22s
```

The 4 failures are all **pre-existing on the base branch** `stage/license-mit-modelforge` — verified by checking out the base and running the same command (same 4 failures, 67 pass since the new test file doesn't exist there). The failures are in `test_campaign_runner.py`, `test_campaigns.py`, and `test_crossover.py` — unrelated subsystems. All 11 new tests in `test_training_backend_curated.py` pass.

To run just the new tests:

```
cd apps/api && /home/saijayanthai/Documents/spark/workspace/model-forge/.venv/bin/pytest tests/test_training_backend_curated.py -v
```

## How to merge

This is a focused two-file production change plus one new test file. Cleanest path is a fast-forward into the target branch.

```
git checkout stage/license-mit-modelforge        # or main, whichever you cut from
git merge --ff-only fix/honor-curated-path
```

Or, if you prefer an explicit merge commit on `main`:

```
git checkout main
git merge --no-ff fix/honor-curated-path -m "Merge: fix(trainer) honor curated_path"
```

No conflicts expected — the branch only adds to `train_adapter` (graph) and `_train_sync_inner` (trainer), both stable for several months.

## How to roll back

If a regression appears in production (e.g. `load_from_disk` raising on a half-written shard from a crashed augment step), the rollback is a single revert:

```
git revert <merge-commit-or-fix-commit>
```

The pre-fix behavior — trainer ignores `curated_path` and always loads OpenOrca — was the prior status quo, so the revert is safe to push without further coordination.

For a **partial** roll-back that keeps the helper + graph propagation but force-disables curated loading (e.g. while debugging a specific shard), set an empty env var-driven kill switch — there is currently no such switch, but adding one would be a 3-line patch in `_resolve_curated_path`:

```python
if os.environ.get("MODELFORGE_DISABLE_CURATED") == "1":
    return None
```

Not added in this PR to keep the surface minimal; flag if you want it.
