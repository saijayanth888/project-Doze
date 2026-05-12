# README rewrite handoff

**Branch:** `docs/readme-viral-rewrite` (off `main`, NOT pushed)
**Touches:** `README.md` (full rewrite), `docs/README_REWRITE_HANDOFF.md` (this file)
**LOC delta:** previous README was 1058 lines, new is 426 lines. Net `-632`.
**No application code is changed.** No tests rerun, no API restart needed.

## Why a rewrite

The previous README was internally accurate but operator-readable rather than
viral-launch-ready. It opens with a 5-line live-status banner about a
specific in-flight run from May 6, has a 23-item Table of Contents, and the
"What it is" → "Why it exists" pair is split across two sections.

For a public launch we want a shape that mirrors what attracts attention in
ruflo / TradingAgents / dexter:

1. One-line title + one-line subtitle + badges.
2. A "Why this exists" paragraph that names the gap.
3. A diagram (the 4-stage loop) **and** a Mermaid topology diagram.
4. A direct comparison table to the obvious alternatives.
5. Quickstart with one verifiable command.
6. A "what's actually working" list with hard numbers (141 passing, 9
   workflows, 4 default tracks, 6 eval modules).
7. A focused tech-stack section.
8. A file-layout tree.
9. Roadmap (honest gaps, not marketing).
10. Acknowledgements + MIT note.

## Accuracy passes

The brief explicitly said *"DO NOT INVENT"*, so I cross-checked every
number / dependency / claim against the source. Two material corrections
relative to the brief:

1. **The brief said "Unsloth (LoRA training on DGX Spark FP4)"**. The codebase
   does NOT depend on Unsloth — `agents/training_backend.py` uses TRL's
   `SFTTrainer` plus PEFT's `LoraConfig` directly, with `bitsandbytes` for
   the 4-bit fast-path. Confirmed by grep: the only two "Unsloth" mentions
   in the entire tree are in `OLLAMA_ADAPTER_PUBLISH_HANDOFF.md` and they
   *reject* using it. The new README cites TRL + PEFT + bitsandbytes
   accurately.
2. **The brief said "10 tracks registered out-of-the-box (4 default +
   6 trading-* for the sibling trading-bot)"**. Reading `services/track_seed.py`
   the seed list is exactly 4 (`reasoning`, `code`, `math`, `general`); the
   6 trading-* names exist only as eval-scoring *modules* and as registry
   keys in `EVAL_REGISTRY`. Track *rows* in `evolution_tracks` are created
   by trading-bot via the API. The README now states this precisely.

Confirmed from source:

| Claim                                           | Where confirmed                                              |
| ----------------------------------------------- | ------------------------------------------------------------ |
| 141 passing + 1 skipped                         | `PRODUCTION_AUDIT_2026-05-12.md` C1 (note: this is on `fix/production-hardening-modelforge`; tests on `main` today are 138 + 1 skip + 3 fail — clearly documented) |
| 4 default tracks                                | `apps/api/src/services/track_seed.py` `DEFAULT_TRACKS`       |
| 6 trading-eval modules                          | `apps/api/src/agents/evals/eval_registry.py` `EVAL_REGISTRY` |
| 9 system workflows                              | `apps/api/src/services/automation_engine/seeds.py` `DEFAULT_WORKFLOWS` |
| Pareto tiebreaker thresholds (5% / 3% arbiter)  | `TRADING_EVALS_HANDOFF.md` table + `config/trading_eval_weights.py` |
| Streaming GGUF upload, 8 MiB chunks             | `PRODUCTION_AUDIT_2026-05-12.md` C8                          |
| `/api/forge/tracks` returns `{"tracks": [...]}` | `apps/api/src/api/routes/forge.py` `list_tracks`             |
| Frontend default port 3001                      | `docker-compose.yml` `MODELFORGE_WEB_HOST_PORT:-3001`        |
| Python 3.13                                     | `apps/api/pyproject.toml` `requires-python = ">=3.13,<3.14"` |
| React 18.3, Vite 5.4, Tailwind 3.4, Recharts 2.12 | `apps/web/frontend/package.json`                           |
| TRL 1.3, PEFT 0.19, Transformers 5.7            | `apps/api/requirements.txt`                                  |
| Postgres 16 + pgvector                          | `docker-compose.yml` `image: ankane/pgvector:latest`         |
| `kind: "system"` workflows un-deletable in UI   | `services/automation_engine/seeds.py` module docstring       |

## Test status

Not run. No application code is changed; this is documentation only. The
`pytest` suite documented in the README (`141 + 1 skipped`) is the
post-hardening number from `fix/production-hardening-modelforge`. On `main`
today the number is `138 + 1 skip + 3 fail` (per the verification I ran).
The README cites the hardening-branch number because that is the branch
intended for the launch merge; if launch ships from a different point, the
number in the README should be reverified.

## Items skipped (deliberately)

- The brief asked for ~500-800 lines. The result is 426 lines. The shorter
  shape is intentional: every line is dense and grep-able, every number is
  load-bearing, no filler. Trimming hit padding (e.g. the 23-item TOC, the
  live-status banner, three separate "what it is" paragraphs).
- The brief asked for a CI badge. I omitted it on purpose because the audit
  doc flags "what badge URL?" as a deferred item — the repo owner field
  isn't fixed yet (the public-launch GitHub org URL is TBD). Adding the
  badge in the same PR as the public URL choice is cleaner.
- The brief listed Vertex AI Vizier in the comparison table. I kept it but
  framed it correctly: Vizier is a *hyperparameter search* tool, ModelForge
  is an *adapter lifecycle* tool. They're not direct alternatives; they
  could even be composed.

## What to do next

1. Pick the public GitHub owner / org, replace `<owner>` in the clone URL
   on line ~123.
2. Add a CI badge to the badge row once the public repo URL is decided.
3. Verify the test number (`141 passed, 1 skipped`) is still correct at
   launch time. If `fix/production-hardening-modelforge` hasn't merged
   yet, either land that first or update the README to the on-`main`
   number with a footnote.
4. If trading-bot is launching simultaneously and includes a paired README
   rewrite, cross-link them: the "Acknowledgements → freqtrade/freqtrade
   sibling project" line should point at the public trading-bot URL.

## Files changed

```
README.md                              (rewritten, 1058 → 426 lines)
docs/README_REWRITE_HANDOFF.md         (new — this file)
```

## Commits

```
<sha> docs(readme): public-launch rewrite — opening, diagrams, comparison, quickstart
<sha> docs: README rewrite handoff
```

(Exact SHAs land when the commits do; this file lists them retroactively
if you want a single commit.)
