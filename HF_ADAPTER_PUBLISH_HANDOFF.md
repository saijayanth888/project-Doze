# adapter.publish_huggingface — Operator Hand-off

Sibling action of `adapter.publish_ollama`. Pushes a promoted LoRA
adapter directory (safetensors + tokenizer + adapter_config + GGUF if
present) to a **private** Hugging Face Hub repo so the trading bot has
a durable, off-host backup of every published adapter.

Wired in series with the local Ollama publisher under the
**"Publish Promoted Adapter to Ollama"** workflow (the workflow keeps
its original name to avoid breaking external references; the new HF
step lands between the local push and the Slack ping).

---

## The 5-stop upload path

```
local adapter dir  →  huggingface_hub.upload_folder  →  create_tag  →  list_repo_refs  →  delete_tag (prune)
   (1)                          (2)                          (3)              (4)                  (5)
```

| Stop | What happens | Failure → status |
|------|--------------|------------------|
| 1 | Locate `<data_root>/adapters/<run_id>/gen-<N>` on disk. Allow-list filters out `optimizer.pt`, `training_args.bin`, `checkpoint-*`. | dir missing → `error` |
| 2 | `HfApi.upload_folder()` streams the dir to a branch named after the resolved revision (e.g. `trading-reflector-v20260512`). Pure HTTP — no local model load. | 413 → `skipped` (quota); 401/403 → `error`; other 5xx → `error: upload_failed` |
| 3 | `HfApi.create_tag()` tags the commit with the same revision string so it survives branch renames. | logged as warning; non-fatal |
| 4 | `HfApi.list_repo_refs()` returns every tag in the repo. We filter to tags matching the role prefix (e.g. `trading-reflector-v*`). | logged as warning; non-fatal |
| 5 | If `len(role_tags) > keep_last_n`, delete the oldest until we're back at the cap. Today's freshly-created tag is never pruned. | logged as warning; non-fatal |

Steps 3-5 are best-effort: a partial failure leaves the upload intact
and surfaces the issue in `output.warning` rather than turning the
workflow row red.

---

## Sample workflow action config

This is the seed shape now baked into
`apps/api/src/services/automation_engine/seeds.py`:

```python
{
    "kind": "adapter.publish_huggingface",
    "config": {
        "repo_id": "Saijayanyh532ai/dgx-trader-adapters",
        "revision_pattern": "{track_id}-v{date}",
        "keep_last_n": 8,
        "include_gguf": True,
        "include_safetensors": True,
    },
},
```

Available placeholders inside `revision_pattern`:

| Token | Value | Example |
|-------|-------|---------|
| `{track_id}` | full track id from the event payload | `trading-reflector` |
| `{role}` | track_id with the `trading-` prefix stripped | `reflector` |
| `{date}` | UTC `YYYYMMDD` at action-run time | `20260512` |
| `{generation}` | int — which evolution generation was promoted | `4` |
| `{run_id}` | full evolution run id | `run-abc123` |

---

## Failure-mode table

| Condition | status | reason in `result.message` |
|---|---|---|
| `HF_TOKEN` not set | `skipped` | `no HF_TOKEN — set in model-forge .env` |
| HF unreachable (DNS / 5xx / timeout on repo probe) | `skipped` | `HF unreachable — adapter remains local` |
| Repo does not exist (404) | `error` | `repo_not_found — create at https://huggingface.co/new` |
| Token has no write scope (401/403) | `error` | `token_lacks_write_scope` |
| Quota exceeded mid-upload (413) | `skipped` | `hf_quota_exceeded — increase plan or prune more aggressively` |
| Upload mid-stream failure (5xx / network drop) | `error` | `upload_failed — HTTP <code>` |
| `create_tag` failure | `ok` | upload succeeded; `output.warning` set |
| `list_repo_refs` or `delete_tag` failure | `ok` | upload succeeded; `output.warning` set |
| `huggingface_hub` not importable | `skipped` | `huggingface_hub not importable — adapter remains local` |

`skipped` is intentionally used for transient infrastructure problems
so the dashboard doesn't show red rows when the local Ollama publish
already succeeded. The operator can re-trigger the workflow once HF
is back.

---

## Test command + result

```bash
cd apps/api && python -m pytest tests/test_publish_adapter_to_hf.py -v
```

Latest run: **21 passed in 0.58s**. Coverage:

- Happy path — repo probe → upload → tag → list → no prune
- `no HF_TOKEN` → `skipped`
- Network error on repo probe → `skipped`
- Repo 404 → `error: repo_not_found` with create hint
- Token 401/403 → `error: token_lacks_write_scope` (parametrized)
- Quota 413 mid-upload → `skipped`
- Server 500 mid-upload → `error: upload_failed`
- Adapter dir missing → `error: adapter_dir_missing`
- Missing payload → `error`
- 10 existing tags + `keep_last_n=8` → exactly 3 pruned (today's tag is +1)
- Other-role tags untouched during prune
- Under-threshold → no prune
- Prune failure → `ok` with warning
- Revision pattern substitution for all placeholders
- Default revision pattern
- `_role_from_track_id` corner cases
- Logger redacts `hf_*` tokens
- Happy-path logs never contain the token
- `files_uploaded` counter excludes `optimizer.pt` / `training_args.bin`
- Action registered in `ACTION_REGISTRY`
- Seed workflow has the HF step between Ollama and Slack

The sibling `test_publish_adapter_to_ollama.py` still passes (16/16) —
the seed assertion was updated to expect the new 3-action sequence.

---

## End-to-end operator verification

### 1. Confirm prerequisites

```bash
cd /home/saijayanthai/Documents/spark/workspace/model-forge
./scripts/check_hf_publish_prereqs.sh
```

The script sources `.env`, calls `whoami-v2` to confirm the token
authenticates, then probes `api/models/<repo_id>` to confirm the
private repo exists. Exit codes are documented at the top of the
script (0/1/2/3/4).

### 2. Trigger a synthetic `track.promoted` event

From inside the api container (or via `make` if that target exists):

```bash
docker exec -it mf-api curl -X POST http://localhost:8000/api/events/emit \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: ${MODELFORGE_API_KEY}" \
  -d '{
    "event_type": "track.promoted",
    "payload": {
      "track_id": "trading-reflector",
      "run_id": "run-test-001",
      "generation": 1
    }
  }'
```

(Substitute the actual emit endpoint if your engine uses a different
route — it's the same one that fires for real evolution promotions.)

### 3. Inspect the workflow run

```bash
docker exec -it mf-api curl -s \
  -H "X-API-Key: ${MODELFORGE_API_KEY}" \
  http://localhost:8000/api/automation/runs?limit=1 | python3 -m json.tool
```

The run trace should show three action results:

1. `adapter.publish_ollama` — `ok` (or `skipped` if Ollama is down)
2. `adapter.publish_huggingface` — `ok` with `repo_url` + `revision`
3. `notify.slack` — `ok` / `skipped` depending on webhook config

### 4. Verify on the Hugging Face side

```bash
git clone https://huggingface.co/Saijayanyh532ai/dgx-trader-adapters
cd dgx-trader-adapters
git fetch --tags
git tag | sort
```

You should see tags shaped like `trading-reflector-v20260512`. Checkout
a tag and `ls` to confirm the adapter files are there:

```bash
git checkout trading-reflector-v20260512
ls -la
# adapter_config.json
# adapter_model.safetensors
# adapter.gguf      (if include_gguf=True and a .gguf exists)
# tokenizer.json
# tokenizer_config.json
# (NO optimizer.pt, NO training_args.bin — explicitly excluded)
```

---

## Quota cap math

Hugging Face's free tier ceiling is ~10 GB per account. The math for
the default retention window:

| Quantity | Size budget |
|----------|-------------|
| Per-version safetensors LoRA adapter | ~150 MB |
| Per-version GGUF blob (`include_gguf=True`) | 30-100 MB |
| Tokenizer + config (negligible) | < 5 MB |
| **Subtotal per version** | **~200-300 MB** |
| Roles in scope (`trading-*`) | 6 |
| Versions retained per role (`keep_last_n`) | 8 |
| **Theoretical max** | **~10-15 GB** |

At the bottom of the band (`include_gguf=False`, lean safetensors) we
land at ~7.2 GB — comfortably under the free-tier ceiling. With GGUF
on AND every role at full retention, we tip just above 10 GB. Two
levers when this becomes a real constraint:

1. Lower `keep_last_n` to 4 (halves the per-role budget).
2. Set `include_gguf=False` on the action config — the GGUF is already
   in local Ollama, so the HF copy is redundant for production
   inference. HF-hosted GGUF is mostly useful for one-off recovery.

The action returns `skipped` with reason `hf_quota_exceeded` if we
ever hit 413 mid-upload, so a busted budget doesn't break the workflow
— it just stops mirroring until the operator prunes by hand.

---

## Future enhancement: hash-check before upload

`huggingface_hub.upload_folder` already does its own SHA-256 dedup for
LFS files (you'll see "skipped because identical content" in the Hub
UI), so this isn't a correctness issue — it's a latency win. If we
ever want to short-circuit the upload entirely:

```python
remote_files = {f.path: f.sha256 for f in api.list_repo_tree(
    repo_id, revision=revision, recursive=True,
)}
local_files = {p.relative_to(adapter_dir).as_posix(): _sha256(p)
               for p in adapter_dir.rglob("*") if p.is_file()}
if remote_files == local_files:
    return ActionResult(status="ok", message="no-op (already at HEAD)")
```

Punted for now — the dedup at the LFS layer makes this a small win,
and the current behaviour (always upload, let HF dedup) is the simpler
mental model.
