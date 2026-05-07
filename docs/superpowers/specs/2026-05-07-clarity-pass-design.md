# Clarity Pass — Models / Champion / Automation

**Date:** 2026-05-07
**Status:** Approved (signal-pass scope, three parallel subagents, commits direct to `main` per testing-mode workflow)

## Goal

Three small UX wins that collectively make the dashboard feel obvious to a non-ML user:

1. **Evolution Start dialog** picks any HuggingFace or Ollama model with a memory-fit guard (replaces the legacy plain `<select>`).
2. **ChampionCard** shows a 4-button "what now?" actions strip and a coaching empty state that explains champions in plain English.
3. **AutomationPage** explains each cron job inline and confirms before destructive runs.

Out of scope: anything that touches the evolution graph, scoring logic, or the in-process AutomationEngine itself. This is pure surface polish on existing data.

---

## Surface A — Evolution Start dialog uses `<ModelPicker>`

**File:** `apps/web/frontend/src/components/dashboard/EvolutionStatus.jsx` (the modal block roughly lines 1040–1230).

**Current state:** Three `<select>` dropdowns let the user pick from local Ollama tags only. No HF search, no memory estimate, no fits-128GB warning.

**Changes:**
1. Replace the three `<select>` dropdowns (Preset tab + Custom tab + advanced override) with a single shared `<ModelPicker value={selectedModel} onChange={setSelectedModel} showMemoryEstimate showPullButton showPresets />`.
2. Underneath the picker, when `validation.fits_128gb === false`, render a yellow warning strip:
   > **Estimated peak {N} GB exceeds the 110 GB safe limit on this box.** Reduce LoRA rank or batch size, or pick a smaller model.

   Start button stays clickable but wrapped in `window.confirm("Estimated peak {N} GB exceeds 110 GB. Run anyway?")`.
3. When `validation.gated === true` AND the model id is not in the local Ollama list, show:
   > **Gated by HuggingFace** — accept the license at https://huggingface.co/{model_id} then ensure `HF_TOKEN` is set in `.env`.
4. Persist the last picked model in `localStorage['mf:last-evolution-model']` so the next dialog open defaults to it.

**Acceptance:**
- Opening the Evolution Start dialog renders the new picker.
- Typing `Qwen/Qwen2.5-3B-Instruct` calls `POST /api/models/validate` and shows the estimate.
- The warning strip appears for any model where `fits_128gb` is false (force test with `meta-llama/Llama-3.1-70B-Instruct`).
- Re-opening the dialog defaults to the last picked model.

---

## Surface B — ChampionCard actions strip + empty-state coaching

**File:** `apps/web/frontend/src/components/dashboard/ChampionCard.jsx` (313 lines).

**Current state:** Renders a champion's per-benchmark scores. No "what can I do with this?" guidance. Empty state is a one-line "No champion yet".

**Changes:**
1. Above the score bars, add a one-line caption:
   > Champion · Gen {N} · promoted {ago} · {model}

   Each segment of the caption gets an `<InfoTooltip>` from `CONCEPT_INFO.champion` / `.generation`.
2. Below the score bars, add a 4-button strip (each lucide icon + label):
   - **Test in Playground** → `navigate('/playground?adapter=' + championAdapterId)`. Playground reads the `adapter` query param and pre-selects it.
   - **Compare vs Base** → `navigate('/playground?compare=base-vs-' + championAdapterId)`. Playground recognises this and opens compare mode.
   - **Start Next Generation** → opens the existing Evolution Start dialog with `existing_adapter` field pre-filled to the champion's adapter path. (Reuses the dialog's existing modal-open hook on the Evolution card.)
   - **View Lineage** → `navigate('/lineage?node=' + championRunId)`. LineagePage reads the `node` query param and focuses that node + opens its detail panel.
3. Replace the empty-state with a coaching block:
   > **No champion yet.**
   > ModelForge promotes an adapter to champion when its scores Pareto-dominate the base on at least one benchmark without regressing others. Click **Start Evolution** to train your first generation.
   > [Start Evolution → primary button]

**Acceptance:**
- Champion card with a real champion shows caption, scores, action strip.
- Clicking each action navigates correctly.
- Empty state shows the coaching block with a working Start Evolution button.

**Note:** PlaygroundPage and LineagePage need to actually read the new query params. If the read path doesn't exist yet, this surface lands the navigation; the receivers are a follow-up. Subagent should add the receivers if the diff is small (each is roughly a `useSearchParams` + a `useEffect` to seed state).

---

## Surface C — AutomationPage clarity

**Files:**
- New: `apps/web/frontend/src/data/automationInfo.js` — keyed reference for the 6 seeded jobs.
- Modified: `apps/web/frontend/src/pages/AutomationPage.jsx` (1193 lines).

**Current state:** Job cards show name, cron, enabled toggle, last run. No explanation of what each job does, when it fires in plain English, or what side effects to expect.

**Changes:**
1. New `automationInfo.js`:
   ```js
   export const AUTOMATION_INFO = {
     evolution_scheduler: {
       title: 'Evolution Scheduler',
       description: 'Kicks off a new evolution run on the configured cadence.',
       when_it_fires: 'Daily at 02:00 UTC by default.',
       what_it_does: 'Reads the latest champion config and starts a new generation aimed at the weakest benchmark.',
       side_effects: 'Holds the GPU for ~2-5 hours. Will refuse to start if a run is already in flight.',
     },
     drift_detection: { ... },
     health_check: { ... },
     weekly_summary: { ... },
     cleanup_archived: { ... },
     daily_eval: { ... },
   };
   ```
   Cover all 6 seeded jobs with the same shape.
2. Each job card gets:
   - One-line `description` in the card header.
   - A "Last run · {timestamp} · {status}" line under the cron preview. The data is already in the API response — surface it.
   - `<InfoTooltip info={AUTOMATION_INFO[job.id]}>` next to the title that renders the full `what_it_does` + `side_effects`.
3. **Run Now** confirmation dialog:
   - Destructive jobs (`cleanup_archived`, `evolution_scheduler`): `window.confirm` with the side-effects summary before calling `POST /jobs/{id}/trigger`.
   - Non-destructive (`health_check`, `drift_detection`, `daily_eval`, `weekly_summary`): run immediately as before, but show a toast confirming queued.
4. Top-of-page banner:
   > **Six in-process automation jobs run on cron schedules and trigger Slack notifications.** Toggle a job off to disable it; click **Run Now** to fire immediately. Configure the Slack webhook in the Slack panel below.

**Acceptance:**
- Each job card shows the description and last-run line.
- Hovering the info icon shows the full explainer.
- Clicking Run Now on `cleanup_archived` triggers a confirmation dialog. Cancelling does nothing; confirming fires the trigger.

---

## Coordination

- Three subagents dispatched in parallel.
- All three share `<InfoTooltip>`, `<LoadingSkeleton>`, `<ModelPicker>` from `apps/web/frontend/src/components/shared/` — already in tree, no conflict.
- A and B both interact with the Evolution Start dialog. A lands first (replaces the picker); B's "Start Next Generation" button opens that same dialog with a pre-filled prop. To avoid a merge race, B waits for A's commit hash before merging — controller serialises the commits if needed.
- Per testing-mode workflow: every commit lands on `main` directly. No feature branches.

## Spec self-review

**1. Placeholder scan** — `automationInfo.js` example has `...` ellipses for the 5 non-evolution_scheduler jobs. The implementing subagent fills them in for all six (instructions in Surface C step 1).

**2. Internal consistency** — Surfaces A and B both reference the Evolution Start dialog. A creates the new picker integration; B opens the same dialog with `existing_adapter` pre-filled. Both can coexist since A doesn't change the modal-open mechanism, only the inner content.

**3. Scope check** — Three independent surfaces. Could each be its own spec but they're all "signal pass" UX wins on adjacent components. One spec is appropriate.

**4. Ambiguity check** — "memory-fit guard" was fuzzy in the brainstorm; made explicit in Surface A (yellow strip + confirm dialog when `fits_128gb` false). "Coaching empty state" was fuzzy; made explicit in Surface B step 3 with the literal text.
