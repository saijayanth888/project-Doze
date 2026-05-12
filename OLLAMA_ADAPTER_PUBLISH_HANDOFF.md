# Ollama Adapter Publish — Operator Handoff

Branch: `feat/ollama-adapter-publish`
Touches: 5 source files, 1 new test file, 1 new operator script, this doc.
Net LOC: ~720 added / ~12 modified (action ≈ 460, tests ≈ 320, registration + condition + seed ≈ 90, script ≈ 80).

This closes the last gap in the trading-bot → model-forge → Ollama
pipeline. When a `trading-*` track promotes, its newly-trained LoRA
adapter is pushed to host Ollama as a versioned model and a
`-current` alias is swung to point at it. Trading-bot can then call
`qwen3:30b-reflector-current` (or `-arbiter-current`, etc.) on its
existing Ollama client path with zero code changes on its side.

---

## The 4-stop publish path

```
runner.py:163 (track.promoted event)
   │
   ▼
event_bus → automation_engine._on_event
   │
   ▼ (workflow matches: trigger_type=event,
   │  pattern=track.promoted, condition startswith trading-)
workflow_runner.execute_workflow
   │
   ▼ action 1: adapter.publish_ollama
   │   1. Locate <data_root>/adapters/<run_id>/gen-<N>/
   │   2. .gguf present?  → use it
   │      else            → run llama.cpp convert_lora_to_gguf.py
   │                       (env: MODELFORGE_LLAMA_CPP_CONVERT /
   │                              MODELFORGE_LLAMA_CPP_DIR)
   │   3. sha256(gguf_bytes), PUT /api/blobs/sha256:<digest>
   │   4. POST /api/create { model, from, adapters }
   │   5. DELETE /api/delete (old alias, 404 OK)
   │   6. POST /api/copy   (alias → versioned name)
   │
   ▼ action 2: notify.slack
       "📦 Adapter published: qwen3-30b-reflector-v20260512
        (alias qwen3-30b-reflector-current)"
```

---

## Path-mapping decision: option (b) — blob upload over HTTP

The action does **not** rely on a shared host/container volume. The
adapter bytes are read by the mf-api process, hashed, and uploaded as
a single PUT to Ollama's `/api/blobs/sha256:<digest>` endpoint, then
referenced by digest in the `POST /api/create` payload. Ollama only
ever sees its own filesystem.

**Why not option (a)?** A bind mount works (the repo already mounts
`./data:/app/data` so the host can read `<repo>/data/adapters/...`
directly, and host Ollama could read it via a second mount), but:

- The repo already uses option (b)'s blob-upload pattern in
  `services/adapter_serve.py:try_create_ollama_model`. Same proven
  shape, same Ollama version compatibility.
- No additional Compose changes required — works on Mac dev hosts
  where host Ollama has no concept of `/app/data` paths.
- Operator never has to remember to keep two volume mounts in sync.
- The blob is content-addressed, so Ollama dedupes across publishes
  of identical adapters.

The tradeoff: a 5–30 GB GGUF round-trips through the loopback once
per publish. On `host.docker.internal:11434` this is local loopback,
~5–10 GB/s — under 5s for typical LoRA-sized adapters
(adapters are tiny; only the base-model fusion would balloon to
30 GB and we don't do that on publish).

---

## Sample Modelfile / create payload

The action does NOT use a string Modelfile. It uses Ollama 0.2+'s
JSON-shaped `POST /api/create`:

```json
{
  "model": "qwen3-30b-reflector-v20260512",
  "from": "qwen3:30b",
  "adapters": {
    "adapter.gguf": "sha256:9b4f...8d2c"
  },
  "system": "You are a trading reflector. Score each LLM call ...",
  "stream": false
}
```

Followed by:

```json
POST /api/copy
{ "source": "qwen3-30b-reflector-v20260512",
  "destination": "qwen3-30b-reflector-current" }
```

Note the base-model slugging: `qwen3:30b` → `qwen3-30b` in the model
name so `ollama list` shows clean names. The `from` field keeps the
original colon-form.

---

## Test command + result

```bash
cd apps/api && PYTHONPATH=src python -m pytest \
    tests/test_publish_adapter_to_ollama.py -v
```

```
14 passed, 1 warning in 0.14s
```

Coverage:

| Test                                                 | Asserts |
|------------------------------------------------------|---------|
| happy path: tags → blob → create → delete → copy     | request sequence, digest, body, alias swing |
| system prompt is forwarded into create body          | payload.system == config.system_prompt |
| Ollama unreachable → status="skipped"                | no torrent of red workflow rows |
| adapter dir missing → status="error"                 | adapter_dir_missing |
| no .gguf + no converter → status="skipped"           | actionable message with env-var hint |
| converter present but fails → status="error"         | gguf_conversion_failed |
| create rejected → status="error", no alias attempt   | ollama_create_failed |
| alias swing fails → status="error", model_name kept  | operator can re-alias |
| missing payload → status="error"                     | track_id + run_id surfaced |
| seed workflow registered + enabled                   | trigger_type, pattern, condition, actions |
| action registered in central registry                | dispatcher can find it |
| startswith condition operator works                  | new operator landed |
| _role_from_track_id strips trading- prefix           | various inputs |
| _render_name substitutes all placeholders            | full pattern coverage |

The 4 pre-existing failures elsewhere in the test suite
(`test_campaigns.py` auth, `test_crossover.py` incompatible parents,
`test_campaign_runner.py` eval-only) are unrelated — they fail on
`main` too and are unchanged on this branch.

---

## Operator validation: end-to-end on a live host

### 1. Pre-flight

```bash
./scripts/check_adapter_publish_prereqs.sh
```

Confirms `mf-api` is running and that `host.docker.internal:11434`
is reachable from inside it. Prints the current Ollama model list so
you have a baseline before the first publish.

### 2. Manually fire a `track.promoted` event

From inside the api container:

```bash
docker exec -it mf-api python -c "
from services.event_bus import bus
bus.publish_nowait('track.promoted', {
    'track_id': 'trading-reflector',
    'run_id': 'run-manual-test',
    'generation': 1,
    'scores': {},
    'new_avg': 0.5,
})
"
```

(You need an actual adapter dir at
`/app/data/adapters/run-manual-test/gen-1/adapter.gguf` for it to do
anything — manual smoke-test only.)

### 3. Verify on Ollama

```bash
curl -s http://localhost:11434/api/tags \
  | jq -r '.models[].name' \
  | grep -E 'qwen3-30b-reflector-'
```

Expect two entries:

```
qwen3-30b-reflector-v20260512
qwen3-30b-reflector-current
```

### 4. Pull from trading-bot

Trading-bot's existing `OLLAMA_BASE=http://localhost:11434` and
model-name config can now reference `qwen3-30b-reflector-current`.

---

## Failure modes + degradation

| Failure                       | ActionResult.status | Workflow row | What the operator does                    |
|-------------------------------|---------------------|--------------|-------------------------------------------|
| Ollama down for maintenance   | `skipped`           | yellow       | Restart Ollama; manually trigger again    |
| `convert_lora_to_gguf.py` not installed | `skipped`  | yellow       | Set `MODELFORGE_LLAMA_CPP_*` env vars or convert manually |
| Converter exits non-zero      | `error`             | red          | Inspect stderr captured in workflow trace |
| Adapter dir missing on disk   | `error`             | red          | Investigate why training didn't persist   |
| `/api/blobs` PUT rejected     | `error`             | red          | Check Ollama disk space / version         |
| `/api/create` rejected        | `error`             | red          | Inspect server response in trace          |
| Alias swing failed            | `error`             | red          | Versioned model still exists; `ollama cp` manually |

The `skipped` vs `error` distinction matters: skipped runs don't
page the operator, errors do. Ollama maintenance windows or
not-yet-installed converters are expected operational states, not
incidents.

---

## What to enable in the frontend after merge

The seed workflow `"Publish Promoted Adapter to Ollama"` is shipped
with `enabled=True`, so once this branch is merged and `mf-api` is
restarted the workflow is live on first boot. On the `/automation`
page in the dashboard the operator will see:

- Name: **Publish Promoted Adapter to Ollama**
- Kind: `system` (un-deletable)
- Trigger: `event: track.promoted`
- Condition: `startswith(track_id, "trading-")`
- Actions: `adapter.publish_ollama` → `notify.slack`

No manual enabling step is required — but if the operator wants to
disable it (e.g. during a debug session where they don't want
adapters auto-published), the standard toggle on the workflow row
works the same way it does for every other system workflow.

---

## GGUF conversion: known limitation

The trainer (`training_backend.py:_train_sync_inner`) saves PEFT-
format `adapter_model.safetensors`, NOT a `.gguf`. Ollama can only
ingest GGUF LoRAs. We chose **not** to bolt Unsloth's
`save_pretrained_gguf` into the trainer (it adds ~3 GB of wheels
and locks us into Unsloth's training path).

Instead, the publish action runs llama.cpp's
`convert_lora_to_gguf.py` as a subprocess when no `.gguf` is found
in the adapter dir. Setup is one-time:

```bash
git clone --depth 1 https://github.com/ggml-org/llama.cpp.git /opt/llama.cpp
pip install -r /opt/llama.cpp/requirements.txt
echo 'MODELFORGE_LLAMA_CPP_DIR=/opt/llama.cpp' >> .env
```

After that, every `track.promoted` for a trading-* track produces a
GGUF on the fly and publishes it. The conversion step is the only
heavyweight component — typically 30–90s per LoRA on DGX Spark.

If you'd rather convert ahead of time (e.g. as part of the trainer's
own pipeline so the publish step is purely network I/O), drop the
`.gguf` into `<data_root>/adapters/<run_id>/gen-<N>/` before the
promotion lands — the action prefers any existing `.gguf` over
running the converter.

---

## Files changed (sourcetree)

```
apps/api/src/agents/actions/__init__.py                       (new)
apps/api/src/agents/actions/publish_adapter_to_ollama.py      (new, ~460 LOC)
apps/api/src/services/automation_engine/actions.py            (+38, registration hook)
apps/api/src/services/automation_engine/conditions.py         (+3, startswith/endswith ops)
apps/api/src/services/automation_engine/seeds.py              (+42, new system workflow)
apps/api/tests/test_publish_adapter_to_ollama.py              (new, ~320 LOC, 14 tests)
scripts/check_adapter_publish_prereqs.sh                      (new)
OLLAMA_ADAPTER_PUBLISH_HANDOFF.md                             (this doc)
```

No changes to `docker-compose.yml`, `training_backend.py`,
`runner.py`, or any frontend code. The `track.promoted` event was
already being emitted from `runner.py:163` — we are only adding the
subscriber.
