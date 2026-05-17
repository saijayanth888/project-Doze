# ModelForge — Claude Code

Autonomous LoRA evolution on DGX Spark (GB10). `docker compose up` in this repo. Sibling: `~/Documents/trading-bot` (consumes Ollama adapter tags via HTTP only).

**Key paths:**

- API / engine: `apps/api/`
- Dashboard: React app in repo README quickstart
- Trading evals: `agents/evals/`
- Design handoffs: `docs/*HANDOFF*`

---

<!-- obsidian-quanta-os:v1 -->
## Obsidian (quanta-os)

Operator vault on this DGX: `~/quanta-os`. Full rules: `~/Documents/setup/obsidian/AGENTS.md`.

When the user says **update obsidian** (or at **end of session** unless they opt out):

1. Update `~/quanta-os/bridge/SESSION_HANDOFF.md` — date, goal, blockers, done-when, read-first repo paths.
2. Update or create notes under `~/quanta-os/300 Projects/modelforge/`; use YAML `canonical_path` for specs under `docs/`.
3. Optionally refresh `~/quanta-os/bridge/AGENT_CONTEXT.md` if operator prefs changed.

**Never** put in the vault: secrets, `.env`, `setup/backups/`, docker volumes, large checkpoints.

```bash
~/Documents/setup/obsidian-setup.sh --vault-only
```

At **session start**, read `~/quanta-os/bridge/SESSION_HANDOFF.md` when working on ModelForge.
<!-- /obsidian-quanta-os:v1 -->
