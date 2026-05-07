# Campaign visibility & Slack reporting — design

**Date:** 2026-05-07
**Author:** sai jayanth (with Claude Opus 4.7)
**Status:** Approved (sections 1-4)

## Problem

A campaign run is opaque from both the dashboard and Slack:

1. **Slack delivers nothing.** The campaign runner calls `automation_engine.notify(..., event_type="campaign")`, but `"campaign"` is not in `automation_settings.notify_event_types`, so `_allowed_event` returns `False` and the message never posts. The webhook itself works.
2. **Notifications, even if delivered, are one-line plaintext.** The user wants a "detailed report" — model list, score breakdown, ETA, per-experiment results — readable from Slack alone over a 17–24 h run.
3. **The dashboard goes dead during a campaign.** `EvolutionStatus` shows the right header (`Campaign · RUNNING`), but the seven-step Evaluate→Record strip is irrelevant for an eval-only baseline, the per-experiment results live only on `/campaigns`, and `EventsFeed` is stuck polling a stale `run-ca6925fd` from a previous evolution session. The user can't watch a 24 h run from `/dashboard`.

The campaign and evolve runners have **drifted into parallel pipelines** — two notify paths, two event lists, two sets of dashboard branches. Fixing only the symptoms above would deepen the rot.

## Goal

Make a campaign indistinguishable from a manual evolution run at the **transport layer** (run-event ring buffer, event bus, Slack helper) so the dashboard and Slack get rich, live coverage of any campaign with widget-level branching only at render leaves. Plus four Block Kit Slack cards that let a researcher read the full state of a 24 h run from their phone.

Out of scope: persisted campaign event log across API restarts, per-sample lm-eval tqdm hook, baseline scores in `ScoreTrends`, n8n inbound triggers.

## Approach (selected: B — unified run-event pipeline)

Treat a campaign as a first-class run with `run_kind="campaign"`, allocate a synthetic `run_id = camp-<plan_id>-<short-uuid>`, and publish all milestones through the **same** `services/run_events.publish` ring buffer + `services/event_bus` topics that the evolution graph already uses. A small Slack subscriber dispatches the four card builders. Dashboard widgets branch on `run_kind` only at render time.

Two alternatives considered:
- **A — Surgical patch (~½ day):** fix allow-list + add card builders + add ladder. Faster but leaves the duplication.
- **C — Full report+digest (~3-4 days):** B plus persisted event log, hourly digest, per-sample tqdm hook, post-run `ScoreTrends` baseline ingestion. Worth doing later in pieces; too much surface to validate at once.

## Architecture

```
                                       ┌──────────────────────────────────────────┐
   POST /api/campaigns/{id}/start  ──► │            CampaignRunner                │
                                       │  • allocates synthetic run_id            │
                                       │      camp-<plan_id>-<short-uuid>         │
                                       │  • _log_event(type, payload, **fields)   │
                                       └────────┬───────────────────┬─────────────┘
                                                │                   │
                                                ▼                   ▼
                                ┌──────────────────────┐  ┌──────────────────────┐
                                │ run_events.publish() │  │ event_bus.publish()  │
                                │ (per-run ring buffer)│  │ (workflow triggers + │
                                │                      │  │  Slack subscriber)   │
                                └──────────┬───────────┘  └──────────┬───────────┘
                                           │                         │
                                           ▼                         ▼
                          GET /api/evolve/{run_id}/events    Slack subscriber →
                          GET /api/lineage/activity          automation_engine.notify_blocks
                          GET /api/campaigns/status          (Block Kit cards)
```

`run_events.publish` is keyed by `run_id` and the existing `/api/evolve/{run_id}/events` endpoint serves any run kind. `EventsFeed.jsx` polls `/api/evolve/{runId}/events` regardless of kind. By giving campaigns a stable synthetic id, they ride the same transport.

`run_kind` is a new field on `/api/campaigns/status` (`"campaign"`) and a virtual one on `/api/evolve/status` (`"evolve"`). The dashboard reads both, picks the active one, and routes its render branches off `run_kind`.

## Event taxonomy

One source of truth — the runner emits via `_log_event(type, message, **extra)`. The helper writes to (a) the existing in-memory campaign event ring buffer (already emits to Activity Feed via `/api/lineage/activity`), (b) `run_events.publish(run_id, ...)`, and (c) `event_bus.publish(f"campaign.{type}", payload)`.

| Event type | When | Slack? | run_events buffer? |
|---|---|---|---|
| `campaign_started` | runner.start() | ✅ start card | ✅ |
| `model_download_started/complete/error` | per repo in pre-flight | — | ✅ |
| `experiment_started` | top of each iter in `_run_campaign` | — | ✅ |
| `benchmark_started` | bench_callback at each lm-eval iter | — | ✅ |
| **`benchmark_complete`** *(new)* | `bench_complete_callback(name, score, stderr)` after each `simple_evaluate` returns | — | ✅ (with score) |
| `experiment_complete` | end of try block | ✅ exp card | ✅ |
| `experiment_failed` | retry-failed branch | ✅ red card | ✅ |
| `experiment_stopped` | `EvalStopped` / status==stopping | ✅ stop card | ✅ |
| `campaign_complete` | end of `_run_campaign` | ✅ summary card | ✅ |

Per-event payload is a flat dict (existing convention). New extras: `score`, `stderr` for benchmark events; `eta_seconds`, `pace_avg_seconds`, `scores` for experiment events; `top_results`, `total_duration_seconds` for the completion event.

## Slack card layouts

All four use `automation_engine.notify_blocks(text, blocks=...)` so the existing `automation_log` row + per-event allow-list filter still apply. Plain-text fallback comes from the existing `notify_blocks` implementation when no webhook is configured.

### 1. Campaign start card (`event_type: campaign_started`)

```
🚀  Campaign started: baseline_all_models
    6 experiments · 6 models · est ~6h
─────────────────────────────────────────
Models:
 • TinyLlama-1.1B-Chat       eval_only
 • Llama-3.2-1B-Instruct     eval_only
 • Llama-3.2-3B-Instruct     eval_only
 • Qwen2.5-3B-Instruct       eval_only
 • Phi-3.5-mini-instruct     eval_only
 • Qwen2.5-7B-Instruct       eval_only
─────────────────────────────────────────
[ Open dashboard ]
```

### 2. Per-experiment card (`event_type: campaign_experiment_complete`) — sent ~6 times per 24 h

```
✅  Experiment 3/6 complete · Llama-3.2-3B-Instruct (62 min)
─────────────────────────────────────────
            score   ± stderr
mmlu        0.624   ±0.011
arc_chal    0.418   ±0.014
hellaswag   0.736   ±0.008
gsm8k_cot   0.218   ±0.012
humaneval   0.054   ±0.018
─────────────────────────────────────────
avg 0.410 · 3/6 done · ETA ~3h 12m (Done by ~11:42 UTC)
[ Open dashboard ]  [ Stop campaign ]
```

### 3. Campaign-complete card (`event_type: campaign_completed`)

```
🏁  Campaign complete: baseline_all_models
    5/6 succeeded · 1 failed · 5h 47m
─────────────────────────────────────────
Top by avg score:
🥇 Qwen2.5-7B-Instruct      avg 0.486
🥈 Llama-3.2-3B-Instruct    avg 0.410
🥉 Phi-3.5-mini-instruct    avg 0.385
   Qwen2.5-3B-Instruct      avg 0.342
   Llama-3.2-1B-Instruct    avg 0.291
   TinyLlama-1.1B-Chat      FAILED (gsm8k_cot OOM)
─────────────────────────────────────────
[ Open dashboard ]  [ Open campaign results ]
```

### 4. Failure card (`event_type: campaign_failed`)

```
🔴  Experiment 4/6 FAILED after retry · Phi-3.5-mini
    Error: CUDA OOM on hellaswag (limit-respected, 11.4 GB peak)
    Campaign continuing with experiment 5/6
[ Open dashboard ]
```

## Allow-list migration

On engine startup, append the four new `campaign_*` event types to `automation_settings.notify_event_types` if they aren't already present. Idempotent, never replaces a user's customised list (only `appends` missing defaults). Surface in the Settings page so a user can disable them later.

## Dashboard surface in campaign mode

When `/api/campaigns/status` returns `status != idle`, the **Evolution Status** card on `/dashboard` morphs:

```
┌─ Evolution Status ─────────────────────────── [Campaign · RUNNING] ┐
│                                                                    │
│   Exp 3/6                          Elapsed                Run id   │
│                                                                    │
│   62:14                            03:47:21         camp-baseline_ │
│                                                     all_models-3a91│
│                                                                    │
│   Llama-3.2-3B-Instruct  · baseline_all_models  · ✓2  ✗0           │
│   ── benchmark progress ──────────────────────────────────────     │
│   ✓ mmlu        0.624   ✓ arc_chal   0.418   ● hellaswag           │
│   ○ gsm8k_cot           ○ humaneval                                │
│                                                                    │
│   ── per-experiment results ──────────────────────────────────     │
│   #  model                          status     avg     duration    │
│   1  TinyLlama-1.1B-Chat            ✓ done    0.291    18m         │
│   2  Llama-3.2-1B-Instruct          ✓ done    0.342    24m         │
│   3  Llama-3.2-3B-Instruct          ● running  …       62m+        │
│   4  Qwen2.5-3B-Instruct                                           │
│   5  Phi-3.5-mini-instruct                                         │
│   6  Qwen2.5-7B-Instruct                                           │
│                                                                    │
│   ETA ~3h 12m · pace 41m/exp · Done by ~11:42 UTC                  │
└────────────────────────────────────────────────────────────────────┘
```

### Components

- **Header badge** — already shipped in commit `318784a`. `Campaign · RUNNING/ENSURING/etc.` in info-blue.
- **Hero numbers** — `Exp X/Y` (current experiment elapsed in big), Elapsed (campaign-wide), `run_id` (camp- prefixed).
- **Benchmark ladder** — new `BenchmarkLadder.jsx`. Replaces the seven-step Evaluate→Record strip while in campaign mode. Driven by a new `current_benchmarks: [{name, score?, stderr?, status: "done"|"running"|"queued"}]` array on the status payload, reset between experiments.
- **Per-experiment results table** — new `CampaignResultsTable.jsx`. Polls `/api/campaigns/{plan_id}/results` every 10 s while campaign is active. Reuses cell formatting from the Campaigns page.
- **ETA strip** — derived client-side from `campaign.results[*].duration_seconds`. Reuses the calc already on the `/campaigns` banner; lifted into a small shared util `lib/campaignEta.js`.
- **EventsFeed** — fix stale-poll bug. Watch `campaign.run_id ?? evolve.run_id`, only poll while `is_running || campaignActive`, unmount cleanly when both go idle.

### Files affected

- New: `apps/web/frontend/src/components/dashboard/BenchmarkLadder.jsx`
- New: `apps/web/frontend/src/components/dashboard/CampaignResultsTable.jsx`
- New: `apps/web/frontend/src/lib/campaignEta.js`
- Edit: `apps/web/frontend/src/components/dashboard/EvolutionStatus.jsx` — mount the two new components in campaign mode, keep existing layout in evolve mode.
- Edit: `apps/web/frontend/src/components/dashboard/EventsFeed.jsx` — smart polling, both run kinds.
- New: `apps/api/src/services/slack_blocks_campaign.py` — four card builders (separate file to keep `slack_blocks.py` focused on evolution).
- New: `apps/api/src/services/campaign_slack.py` — small subscriber that listens on `campaign.*` event_bus topics and dispatches to `notify_blocks`.
- Edit: `apps/api/src/services/campaign_runner.py` — allocate synthetic `run_id` on `start()`, publish to `run_events` + `event_bus` from `_log_event`, add `bench_complete_callback`, expose `current_benchmarks` + `run_kind` in `get_status()`.
- Edit: `apps/api/src/agents/eval_backend.py` — add `bench_complete_callback(name, score, stderr)` parameter alongside existing `bench_callback`.
- Edit: `apps/api/src/services/automation_engine/engine.py` — startup hook that appends missing campaign event types to `notify_event_types`.

## Failure modes

| Failure | Behavior |
|---|---|
| Slack webhook 4xx/5xx | Logged at `WARN` (existing); next event tries again. Campaign continues. |
| Allow-list excludes `campaign_*` | Migration adds the four new types if missing. User overrides preserved. |
| Block Kit builder raises | Caught in `campaign_slack` subscriber; falls back to plain `notify(text)` with the same headline. Campaign continues. |
| `event_bus.publish` raises | Already swallowed; dashboard still reads from `run_events` ring buffer. |
| `run_events` buffer evicted (>200 events) | Dashboard polls latest 200 via `since=`; older events still in DB-backed `campaign_results`. |
| API restart mid-campaign | In-memory state lost (existing limitation). New on-startup hook flips orphan `running` rows in `campaign_plans` to `failed (api_restart)` so the UI doesn't show a phantom run. |
| lm-eval crashes mid-benchmark | Caught in existing per-bench try/except; benchmark scored 0; experiment continues. `benchmark_complete` event still published with `score=0, status="error"` so the ladder shows an X. |
| User clicks Stop | Existing cooperative-stop flow; now also publishes `experiment_stopped` event + a 🛑 Slack card via `notify_blocks` (no full results card). |

## Testing

### Unit (pytest, async)
1. `test_slack_blocks_campaign_started` — assert text + blocks JSON shape; `mrkdwn` rendering of model list.
2. `test_slack_blocks_campaign_experiment_complete` — score table aligned, ETA computed, no NaN with empty results.
3. `test_slack_blocks_campaign_completed` — top-3 ranking correct, failed experiments shown without average.
4. `test_event_taxonomy_publishes_to_run_events_buffer` — drive `_log_event` through a fake runner, assert `run_events.list_events(synthetic_id)` returns expected sequence.
5. `test_allow_list_migration_idempotent` — run migration twice, custom user setting preserved.

### Integration (pytest, async with `MockEvalBackend`)
6. End-to-end: kick off a 2-experiment campaign with the mock backend, assert: `campaign_started` event published, `experiment_complete` events published with correct scores, `campaign_complete` event published, `automation_engine.notify_blocks` called four times (start + 2× exp_complete + complete).

### E2E (Playwright)
7. `dashboard-campaign.spec.ts` — start mock campaign via API, navigate to `/dashboard`, assert: ladder visible, per-experiment table populates, ETA strip appears, `EventsFeed` widget unmounts old poll cleanly.

## Out of scope (carved off as follow-ups)

- Persisted `campaign_events` table (durable replay across API restarts) — Approach C item.
- Per-sample lm-eval tqdm hook (live "1234 / 5678 samples") — Approach C item.
- Post-run baseline scores in `ScoreTrends` — separate small ticket; not blocking visibility.
- Campaign event integration with n8n inbound triggers — explicitly excluded by the user ("we don't need n8n").
- Hourly digest if no experiment finishes within an hour — not requested in section 2; revisit if 24 h runs ever stall.
