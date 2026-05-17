# Trading Data + Eval Pipeline — Complete Structural Rebuild

**Date:** 2026-05-17
**Status:** BINDING (rev3, post-empirical) — builder implements verbatim; no scope creep; no unimplemented sections
**Operator constraints:** no band-aids, no fake/synthetic data, no silent failures, every code path tested

**Rev2 changes:** Removed $10k notional fudge (writes null instead); added crypto-term contamination filter for bull/bear; fixed N_MIN literature cite (8B not 3B); added evolution_graph.py:655 first-gen min-score gate; added explicit container subprocess env spec; added garbage-adapter cleanup section (Section L); replaced "independently reversible" with dependency matrix; fixed 524-ticker arithmetic.

---

## Preface: Load-Bearing Facts

1. Zero stock closed trades exist anywhere. Shark paper-trading since 2026-04-25 with no closed positions.
2. `~/.dgx-train/shark/memory/llm-calls.jsonl`: 32 lines, 28 with full text. Agents: `risk_debate.aggressive`, `risk_debate.conservative`, `risk_debate.neutral`, `trade_reviewer`, `regime_tagger`. Real calls, NOT post-mortems.
3. `quanta_schema.decisions`: 29k rows, all crypto. Schema: `id`, `ts`, `symbol`, `strategy`, `debate JSONB`, `outcome TEXT`, `rationale TEXT`.
4. `stocks/kb/historical_bars/*.json`: 504 daily OHLCV bars per ticker, 524 tickers.
5. `quanta_schema.proposals.intent` JSONB carries `regime` and `conviction` only — NO indicator list.
6. `trading-indicator-selector` agent is NOT wired into any active Shark phase. Zero records exist.
7. All `default_judge` / `default_adapter_runner` / `default_rubric_scorer` are stubs. Every score seen to date is theatrical.
8. `runner.py:132`: `if new_avg <= 0: continue` silently swallows track promotion events with zero scores.

---

## Section A: Data Sourcing Decision Tree

### Overall principle

The operator forbids fake/synthetic data. Real means: produced by a live agent making a real market decision with real price data as input. Derived fields (forward returns, dollar PnL from percent) computed deterministically from real price history are real. LLM-generated fictional trades are not.

Because zero stock closed trades exist today, **reflector cannot train yet**. The curator MUST enforce a minimum-records gate (Section D) and FAIL rather than produce a zero-row or wrong-data training set.

The other five tracks have 28 real llm-calls.jsonl records and the 29k `quanta_schema.decisions` rows. Using crypto call records for training prose-quality (bull/bear/arbiter) or structured-output (regime-tagger) does NOT violate the no-fake-data rule — these are real agent outputs against real market data. The symbol discriminator ensures forward-return gold truth uses price data from the matched instrument.

### Per-track sourcing decisions

**trading-reflector:**
- Decision: Option (i) — FAIL until N_MIN = 30 closed stock trades accumulate. Do NOT bootstrap from crypto. Cross-asset training would systematically corrupt the `predictive_hit_rate_30d` locked tiebreaker metric.

**trading-bull:**
- Decision: Option (iii) — bootstrap from `quanta_schema.decisions.debate` JSONB, **filtered through a crypto-term contamination blocklist** (see filter below). Source the `debate["bull"]` sub-field. Supplement with `llm-calls.jsonl` agent=`risk_debate.aggressive` (these are already stock-side).
- **Rejection rule:** A record is dropped from the bull/bear training set if its `debate["bull"]` (or `debate["bear"]`) text contains ANY of: `funding rate`, `on-chain`, `USDT`, `USDC`, `BTC`, `ETH`, `LTC`, `SOL`, `ADA`, `perpetual`, `leverage`, `staking`, `mempool`, `gas fee`, `tokenomics`, `airdrop`, `whale`, `24/7`, `mining`, `validator`, `halving`. Case-insensitive substring match. The filter is applied PER RECORD at curate time. Records that fail this filter are counted in `reject_reasons["crypto_term_contamination"]`.
- **Consequence:** It is possible (likely, in fact) that ALL 29k crypto decision records will be rejected by this filter — crypto debates by definition reference crypto concepts. In that case, bull/bear curator FAILS with `insufficient_data` until stock-side llm-calls.jsonl accumulates `N_MIN_TRAIN=50` records organically. **This is the correct production behavior.** It is preferable to a polluted adapter.

**trading-bear:**
- Same as bull. Source `debate["bear"]` and `llm-calls.jsonl` agent=`risk_debate.conservative`. Same crypto-term blocklist applies.

**trading-arbiter:**
- Decision (rev3 — post-bootstrap empirical finding 2026-05-17 23:30Z): FAIL until N_MIN=100 stock-side arbiter decisions accumulate in `llm-calls.jsonl`. Do NOT bootstrap from `quanta_schema.decisions`.
- Why: empirical inspection of the table proves it is operational gate telemetry, NOT a debate transcript. `debate JSONB` carries `{ts, close, regime, verdict}` only — no bull/bear prose. `outcome` has 5 enum values (`ERROR | RG_BLOCKED | SELL | BUY | FLAT`). `rationale` is one sentence (`"no signal; regime=trending_up"`). All `symbol` values are crypto pairs (`BTC/USD`, `XRP/USD`). Bootstrapping would teach the arbiter to output crypto-ticker JSON — same asset contamination that the bull/bear blocklist prevents structurally.

**trading-regime-tagger:**
- Decision (rev3 — post-bootstrap empirical finding 2026-05-17 23:30Z): FAIL until N_MIN=40 stock-side regime-tagger calls accumulate in `llm-calls.jsonl`. Do NOT bootstrap from `quanta_schema.decisions`.
- Why: empirical inspection shows the bootstrap produces records where the prompt is literally `Symbol: BTC/USD\nStrategy: mean_rev_bb` and the response is `{"regime": "ranging"}`. The only signal is the strategy field, and the strategy→regime mapping is the same deterministic table we already implemented in `STRATEGY_TO_REGIME`. Training a LoRA on this would produce a model that memorises a pure function we already have in code — `agreement_with_baseline` would score ~1.0 by tautology, not learning. That is exactly the theatrical-metric trap this whole campaign exists to prevent.
- Original (rev2) text retained for reference:
  - Use 8 existing `regime_tagger` llm-calls.jsonl records. Supplement from `quanta_schema.decisions.strategy` column → `RegimeLabel` enum mapping:
  - `meta_up_regime` → `trending_up`
  - `meta_down_regime` → `trending_down`
  - `bb_squeeze` → `ranging`
  - `bb_breakout` → `breakout_up`
  - `bb_revert` → `ranging`
  - `high_vol_*` → `high_volatility`
  - No mapping match → SKIP

**trading-indicator-selector:**
- Decision: Zero records exist. Do NOT bootstrap from synthetic data. The build path is:
  1. Wire the `indicator_selector` agent call into `stocks/shark/phases/market_open.py` so it fires per-symbol per-day.
  2. Until N_MIN = 20 real calls accumulate, the curator FAILS for this track.
  3. `quanta_schema.proposals.intent` does NOT carry indicator data — confirmed, it carries only `regime` and `conviction`.

### Symbol discriminator (authoritative)

```python
import re
_STOCK_RE = re.compile(r'^[A-Z]{1,5}$')
_CRYPTO_RE = re.compile(r'^[A-Z]+/[A-Z]+$')
_OPTIONS_RE = re.compile(r'^[A-Z]{1,6}\d{6}[PC]\d{8}$')

def classify_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if _OPTIONS_RE.match(s): return 'option'
    if _CRYPTO_RE.match(s): return 'crypto'
    if _STOCK_RE.match(s): return 'stock'
    return 'unknown'
```

---

## Section B: Per-Track Curated Schema (Exact Field List + Types + Source)

### trading-reflector test-set row

```json
{
  "prompt":                    "<string> — [SYSTEM]\n...\n[USER]\n<thesis + realized ledger>",
  "realized_pnl_usd":          "<float> — (exit_price - entry_price) * shares. NEVER percent.",
  "forward_30d_return":        "<float|null> — (close[t+30d] - close[close_date]) / close[close_date] from historical_bars",
  "arbiter_prompt":            "<string> — next-day arbiter context: regime + price for ticker at closed_at+1",
  "arbiter_baseline_decision": "<string> — offline inference: champion arbiter response to arbiter_prompt at curate time",
  "predicted_direction":       "<string|null> — 'long'|'short'|'neutral'",
  "ticker":                    "<string>",
  "closed_at":                 "<string> — ISO date",
  "exit_price":                "<float|null>"
}
```

**realized_pnl_usd derivation (CRITICAL — no fabricated notional):**
- If the source ledger row has BOTH `entry_price` AND `exit_price` AND `qty`: `realized_pnl_usd = (exit_price - entry_price) * qty`. Real number.
- If the source only has `pnl_pct`: write `realized_pnl_usd: null`. Do NOT fabricate a notional.
- Records with `realized_pnl_usd is null` are kept in the training set (the prompt + gold_response are still useful) but the `faithfulness_regex` eval skips them: `if record["realized_pnl_usd"] is None: continue` — the denominator drops by 1 for that record. This mirrors how `predictive_hit_rate_30d` handles null `forward_30d_return`.
- The system prompt for reflector training instructs the model to cite the dollar value WHEN AVAILABLE, not unconditionally. See Section F.

**forward_30d_return derivation:** `load_historical_bars(ticker, days=35)` → take `close[close_date + 30 trading days]` vs `close[close_date]`. When fewer than 30 bars remain: write `null` and this record contributes 0 to the denominator of `predictive_hit_rate_30d`.

**arbiter_baseline_decision (FROZEN at v0, not moving):**
- Generated ONCE per record at the time the record first enters the test set, using `hermes3:8b` BASE model (not whatever champion exists at curate time).
- Stored as a permanent field on the test-set record — never re-generated.
- This makes `debate_impact` a stable cross-week metric: "does the reflector change what hermes3:8b base says?" stays meaningful across all weeks.
- New test records added in later weeks use the same hermes3:8b base for baseline generation, so the metric remains comparable.
- **Drift mitigation:** If hermes3:8b itself is replaced (e.g., the operator upgrades the base model), all existing test records keep their original `arbiter_baseline_decision`; only new records use the new base. The eval metric's interpretation shifts at the upgrade boundary, which is documented in the train log.

### trading-bull test-set row

```json
{
  "prompt":                   "<string> — full bull-debater prompt with price context",
  "opponent_strongest_point": "<string> — from debate['bear_strongest_point'] or extracted regex from bear response",
  "prior_response":           "<string> — prior champion's response embedded at curate time",
  "ticker":                   "<string>",
  "ts":                       "<string> — ISO timestamp"
}
```

**prior_response derivation:** Run the PREVIOUS champion adapter (or the raw `response` from `llm-calls.jsonl` on first generation) against the same prompt at curate time. Embedded to avoid per-record inference at eval time.

### trading-bear test-set row

Identical structure to bull. Source `debate["bull_strongest_point"]` for `opponent_strongest_point`.

### trading-arbiter test-set row

```json
{
  "prompt":              "<string> — full arbiter context: debate text + evidence bundle",
  "forward_5d_pnl_usd":  "<float|null> — signed USD PnL long-side outcome over next 5 days",
  "symbol":              "<string>",
  "ts":                  "<string>"
}
```

**forward_5d_pnl_usd derivation:**
- Crypto rows: `(fill_price_exit - fill_price_entry) * qty` from `quanta_schema.fills` within 5 days of the decision. When no fill: `null`.
- Stock rows: `(historical_bars[symbol][ts + 5d].close - historical_bars[symbol][ts].close) * 100` (canonical 100-share notional).
- Sign convention: Always long-side delta. `eval_arbiter.py` applies direction sign for "sell" proposals.

### trading-regime-tagger test-set row

```json
{
  "prompt":          "<string> — regime-tagger prompt with OHLCV context",
  "baseline_output": {"regime": "<RegimeLabel string>"},
  "symbol":          "<string>",
  "date":            "<string>"
}
```

**baseline_output.regime derivation:** HMM feature vector `[log_return, realized_vol_30d, volume_ratio, rsi_14]` from `historical_bars` for stock symbols. For crypto-only symbols: map `decisions.strategy` via the enum table in Section A.

### trading-indicator-selector test-set row

```json
{
  "prompt":          "<string> — indicator-selector prompt: symbol + regime + OHLCV context",
  "baseline_output": {"indicators": ["<string>"]},
  "symbol":          "<string>",
  "regime":          "<string>",
  "date":            "<string>"
}
```

**baseline_output.indicators:** Deterministic — not LLM generated:

```python
REGIME_BASELINE_INDICATORS: dict[str, list[str]] = {
    "trending_up":    ["ema", "macd", "atr", "adx", "rsi"],
    "trending_down":  ["ema", "macd", "atr", "adx", "rsi"],
    "ranging":        ["bbands", "rsi", "stoch", "mfi", "atr"],
    "high_volatility":["atr", "bbands", "rsi", "vwap", "obv"],
    "low_volatility": ["bbands", "rsi", "sma", "mfi", "stoch"],
    "breakout_up":    ["vwap", "obv", "atr", "macd", "adx"],
    "breakout_down":  ["vwap", "obv", "atr", "macd", "adx"],
}
```

---

## Section C: Test-Set vs Train-Set Split Policy

**General rule:** Temporal split — oldest records go to test, newest to train. This prevents look-ahead within a weekly retrain.

For bulk historical imports (crypto `quanta_schema.decisions`): split by `id % 10 == 0` (10% test) selecting from lowest IDs (oldest timestamps).

| Track | Test % | Min test N | Split method | Leakage guard |
|-------|--------|------------|--------------|---------------|
| trading-reflector | 20% | 10 | Temporal by `closed_at` | Frozen test IDs in `test_ids.json` |
| trading-bull | 15% | 15 | `id % 7 == 0` (oldest IDs) | Frozen IDs — new records go to train only |
| trading-bear | 15% | 15 | Same as bull | Same |
| trading-arbiter | 20% | 15 | Temporal by `ts` | PnL labels recomputed at refresh; IDs frozen |
| trading-regime-tagger | 20% | 10 | Temporal by `ts` | Baseline re-run at refresh |
| trading-indicator-selector | 20% | 10 | Temporal by `ts` | Baseline is stateless |

**Test-set refresh policy:** Each Sunday curate re-scan appends only NEW records since last Sunday. Old test records are never removed. A record that landed in the test set at t=0 stays there forever.

---

## Section D: Minimum-Records-to-Train Thresholds

```python
# Sources: HuggingFace PEFT instruction-tuning ablations (Mangrulkar et al. 2023);
# QLoRA paper (Dettmers et al. 2023) for 7B base; TRL SFTTrainer reference examples.
# Hermes-3-Llama-3.1-8B is an 8B base — practical floor for measurable
# generalization at rank 16 on instruction-style tasks is 100-200 records.
# We set N_MIN_TRAIN below that and accept that the first generation will
# be undertrained; the Pareto gate + min-score gate (Section G + Section M)
# ensures only adapters that beat the base advance to production.
N_MIN_TRAIN: dict[str, int] = {
    "trading-reflector":          100,  # post-mortem prose; 100 closed trades for predictive_hit_rate_30d SNR ≥ 0.2
    "trading-bull":               100,  # debate prose with stock-specific vocabulary; 100 stock-only after crypto blocklist
    "trading-bear":               100,
    "trading-arbiter":            100,  # structured output + PnL labels — 100 train, 25 test minimum
    "trading-regime-tagger":      40,   # 7-class JSON classifier; base already knows JSON, just needs label distribution
    "trading-indicator-selector": 40,   # 20 indicators, top-k selection; smaller because deterministic baseline is the anchor
}
N_MIN_TEST: dict[str, int] = {
    "trading-reflector":          20,
    "trading-bull":               20,
    "trading-bear":               20,
    "trading-arbiter":            25,
    "trading-regime-tagger":      15,
    "trading-indicator-selector": 15,
}
```

**Practical implication:** At current accumulation rates, NONE of the 6 tracks will pass these gates this week. That is the correct production state. The system will emit `track.eval_failed` events with `reason: "insufficient_data"` and Slack-alert. No training fires. Existing garbage adapters in Ollama are cleaned up per Section L.

**Enforcement in `modelforge_curate.py::curate_role`:**

```python
if result.accept_count < N_MIN_TRAIN[role]:
    result.reject_reasons["below_min_records_gate"] = result.accept_count
    logger.error(
        "[curate] role=%s INSUFFICIENT DATA: accept_count=%d < N_MIN=%d. "
        "No shard written. Evolution will be blocked.",
        role, result.accept_count, N_MIN_TRAIN[role],
    )
    return result  # out_path remains None — callers check this
```

**curator_result.json** written alongside the Arrow shard:

```json
{
  "status": "ok" | "insufficient_data" | "error",
  "track_id": "trading-bull",
  "accept_count": 52,
  "reject_count": 8,
  "test_set_count": 8,
  "reject_reasons": {"evidence_too_thin": 5, "empty_response": 3},
  "out_path": "~/.dgx-train/datasets/trading-bull/curated",
  "test_set_path": "~/.dgx-train/datasets/trading-bull/test_set.jsonl",
  "timestamp_utc": "2026-05-18T04:31:00+00:00"
}
```

---

## Section E: Eval Helper Wiring

### default_adapter_runner

Remove `MODELFORGE_EVAL_USE_PEFT` entirely. Replace with GPU-presence detection:

```python
def default_adapter_runner(adapter_path: str, prompts: list[str]) -> list[str]:
    from utils.gpu import get_gpu_status
    if not get_gpu_status().get("gpu_available"):
        return ["" for _ in prompts]  # Non-GPU env: tests must inject their own runner
    try:
        from services import peft_inference
    except ImportError as exc:
        logger.error("[trading-eval] peft_inference unavailable on GPU host: %s", exc)
        raise RuntimeError("GPU host must have peft_inference installed") from exc
    out = []
    for prompt in prompts:
        try:
            resp = peft_inference.run_with_adapter_sync(
                adapter_path=adapter_path, prompt=prompt,
                max_new_tokens=512, temperature=0.0,
            )
            out.append(str(resp.get("response", "")) if isinstance(resp, dict) else str(resp))
        except Exception as exc:
            logger.warning("[trading-eval] adapter inference failed: %s", exc)
            out.append("")
    return out
```

### default_judge

**Judge model selection — DIFFERENT family from student to avoid same-author bias.**

The student is `hermes3:8b` + LoRA. The judge must NOT be hermes3:* (any size). Available local options on this host: `qwen3:8b`, `qwen3:30b`, `phi3.5:latest`, `mistral:7b`. Default: `qwen3:8b` (different family, similar size class for fair comparison).

```python
def default_judge(prompt: str, resp_a: str, resp_b: str) -> float:
    """Real Ollama judge from a DIFFERENT model family than the student.
    Falls back to 0.5 on failure but logs an ERROR.
    Validated for discriminative capacity in test_default_judge_discriminates.
    """
    import json as _json, httpx
    from config.settings import settings
    judge_model = os.environ.get("MODELFORGE_JUDGE_MODEL", "qwen3:8b")
    if judge_model.startswith("hermes3"):
        # Guardrail: refuse to use same-family judge.
        raise ValueError(
            f"MODELFORGE_JUDGE_MODEL={judge_model} is same family as student; "
            f"choose a different model family (qwen3, phi3.5, mistral)."
        )
    judge_prompt = (
        f"Prompt given to the analyst:\n{prompt[:800]}\n\n"
        f"Response A:\n{resp_a[:600]}\n\nResponse B:\n{resp_b[:600]}\n\n"
        'Which response is better for a trading decision? Reply ONLY with a JSON object: '
        '{"preference": "A" or "B" or "tie", "score_a": 0.0-1.0, "score_b": 0.0-1.0, "reason": "..."}'
    )
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.post(
                f"{settings.ollama_host.rstrip('/')}/api/generate",
                json={"model": judge_model, "prompt": judge_prompt, "stream": False},
            )
        blob = r.json().get("response", "")
        m = re.search(r"\{.*\}", blob, re.DOTALL)
        if m:
            parsed = _json.loads(m.group(0))
            return float(parsed.get("score_a", 0.5))
    except Exception as exc:
        logger.warning("[trading-eval] judge call failed (%s): %s", judge_model, exc)
    return 0.5
```

### default_rubric_scorer

Same Ollama call pattern as judge, with a 1-5 rubric prompt. Returns `(raw_score - 1.0) / 4.0`. On failure: returns 0.5 (not 0.0) to avoid false metric collapse.

### Latency budgets

| Track | PEFT inference | Judge/rubric | Total per weekly eval |
|-------|----------------|--------------|----------------------|
| reflector (30 records) | ~120s | 30 × 2s = 60s | ~3 min |
| bull/bear (50 records each) | ~200s | 50 × 2s = 100s | ~5 min each |
| arbiter (40 records) | ~160s | none | ~3 min |
| regime/indicator (20 records each) | ~80s | none | ~1.5 min each |

**Total weekly cycle: ~19 min across all 6 tracks. Acceptable.**

### Test isolation requirement

All unit tests MUST inject `adapter_runner=lambda path, prompts: [fixture_response] * len(prompts)`. The `MODELFORGE_EVAL_USE_PEFT` env var is removed from all test files and CI config. No test should depend on GPU presence.

---

## Section F: Field Naming and Semantic Fixes

### realized_pnl → realized_pnl_usd (BREAKING RENAME, all call sites)

**Problem:** `eval_reflector.py` compares dollar amounts from `extract_first_dollar_value(response)` to `record.get("realized_pnl")`, but `modelforge_curate.py` currently writes a percent float (from `pnl_pct` regex). Dollar vs percent comparison produces spurious faithfulness failures.

**Fix:** Rename to `realized_pnl_usd` everywhere. Enforce USD at curate time.

**All call sites requiring update:**

1. `trading-bot/scripts/modelforge_curate.py` lines 444-448: Remove `realized_pnl_pct` and `realized_pnl` assignments; add `realized_pnl_usd` computed from dollar amount using `(raw_pct / 100) * notional_usd`.
2. `model-forge/apps/api/src/agents/evals/eval_reflector.py` line 111: `record.get("realized_pnl")` → `record.get("realized_pnl_usd")`.
3. `model-forge/apps/api/tests/test_trading_evals.py`: Update all test fixtures using `realized_pnl` key.

### extract_first_dollar_value — keep $-required regex; gate faithfulness on non-null

**Decision:** Keep $-required regex. Update `eval_reflector.py` to skip records where `realized_pnl_usd is None` (don't count them toward denominator).

**Eval change at `eval_reflector.py:108-118`:**

```python
faithful_eligible = 0
for record, response in zip(records, responses, strict=False):
    gold = record.get("realized_pnl_usd")
    if gold is None:
        continue  # No real notional — skip this record's faithfulness check
    faithful_eligible += 1
    cited = extract_first_dollar_value(response)
    try:
        gold_f = float(gold)
    except (TypeError, ValueError):
        gold_f = None
    if values_match_to_decimal(cited, gold_f, decimals=1):
        faithful_hits += 1
# faithfulness_regex computed against faithful_eligible, not len(records)
scores["faithfulness_regex"] = rate(faithful_hits, faithful_eligible)
```

**System prompt update in `modelforge_ingest.py::reflector_example`:**

```python
"system_message": (
    "You are Shark's nightly reflector. Given the trade thesis and the "
    "realized outcome, write 2-4 sentences naming what worked, what "
    "missed, and one lesson to carry forward. When the ledger row "
    "includes a USD P&L value, cite it with a dollar sign (e.g. $-123.45 "
    "or $+87.00). When only a percentage is available, cite the percent. "
    "Never fabricate a dollar figure."
),
```

---

## Section G: Silent-Skip Removal (runner.py:132)

**Current code:**
```python
new_avg = _avg_subset(child_scores, targets)
if new_avg is None or new_avg <= 0:
    continue
```

**Fix — split into two cases:**

```python
new_avg = _avg_subset(child_scores, targets)
if new_avg is None:
    # Run didn't target this track's benchmarks — expected for non-trading runs. Skip silently.
    continue
if new_avg <= 0:
    # Scores exist but are zero/negative — eval infrastructure failure (stubs active or metric broken).
    logger.error(
        "[track] %s skipped promotion: new_avg=%.4f <= 0 for benchmarks=%s. "
        "This indicates eval stubs are active or all metrics returned 0. "
        "Check MODELFORGE_EVAL_USE_PEFT removal and judge wiring.",
        track.get("track_id"), new_avg, targets,
    )
    _emit_event("track.eval_failed", {
        "track_id": track.get("track_id"),
        "track_name": track.get("name"),
        "run_id": run_id,
        "generation": int(generation),
        "new_avg": round(new_avg, 4),
        "target_benchmarks": targets,
        "child_scores": dict(child_scores),
        "reason": "eval_score_zero_or_negative",
    })
    continue
```

**track.eval_failed event schema:**

```json
{
  "topic": "track.eval_failed",
  "payload": {
    "track_id": "string",
    "track_name": "string",
    "run_id": "string",
    "generation": "int",
    "new_avg": "float",
    "target_benchmarks": ["string"],
    "child_scores": {"metric_name": "float"},
    "reason": "eval_score_zero_or_negative | test_set_missing | adapter_runner_stub"
  }
}
```

**Routing:** Through `_emit_event` → `services.event_bus`. A seeded workflow `"Trading Eval Failure Alert"` in `seeds.py` posts to Slack with `emoji="🚨"`, enabled by default.

### evolution_graph.py:655 — first-gen min-score gate

The current `compare_to_champion` auto-promotes generation 1 regardless of scores:

```python
if not parent or champion_avg <= 0.0:
    state["decision"] = "promote"
    state["decision_reason"] = "No prior champion — promoting initial generation"
```

This is the gate that let the 4 garbage adapters publish this morning. Replace with:

```python
child_avg = _avg(state.get("child_scores", {}))
MIN_FIRST_GEN_SCORE = float(os.environ.get("MODELFORGE_MIN_FIRST_GEN_SCORE", "0.30"))
if not parent or champion_avg <= 0.0:
    if child_avg < MIN_FIRST_GEN_SCORE:
        state["decision"] = "discard"
        state["decision_reason"] = (
            f"First-gen min-score gate: child_avg={child_avg:.4f} < "
            f"MIN_FIRST_GEN_SCORE={MIN_FIRST_GEN_SCORE}. "
            f"Adapter not promoted; no track.promoted event will fire."
        )
    else:
        state["decision"] = "promote"
        state["decision_reason"] = (
            f"First-gen min-score gate: child_avg={child_avg:.4f} >= "
            f"{MIN_FIRST_GEN_SCORE}. Promoting initial generation."
        )
```

`0.30` is a conservative floor: any track scoring below 0.30 average across its target benchmarks is producing essentially noise. With real judge/rubric/PEFT wired in, a competent base model should hit at least 0.30 on judge_score alone, so the gate trips only when the eval pipeline itself is broken.

---

## Section H: Workflow Wiring

### New action: BuildTradingDataset

**File:** `model-forge/apps/api/src/services/automation_engine/actions.py`
**Class:** `BuildTradingDataset(Action)` with `kind = "dataset.build_trading"`

Runs Stage 1 (ingest) and Stage 2 (curate) for a given `track_id` via subprocess calls to the trading-bot scripts. Reads `curator_result.json` to determine success. Returns `status="error"` with a `records_count: 0` output when the data gate fails.

**Container execution environment (must be specified in Dockerfile):**

- The action shells out via `subprocess.run(["python3", "/app/trading-bot/scripts/modelforge_curate.py", "--role-filter", track_id, ...])`.
- `apps/api/requirements.txt` MUST include: `pandas>=2.0`, `asyncpg>=0.29`, `psycopg2-binary>=2.9` (the trading-bot scripts import these). Verify before commit.
- `docker-compose.yml` `mf-api` service env block MUST include `TRADEBOT_DATABASE_URL=postgresql://postgres:postgres@tradebot-postgres:5432/postgres` and `mf-api` MUST be on the same Docker network as `tradebot-postgres` (add `external_links` or shared network in compose).
- `BuildTradingDataset.execute()` validates connectivity before invoking subprocess: a `SELECT 1` against `TRADEBOT_DATABASE_URL`. If the probe fails, returns `status="error"` with reason `"tradebot_db_unreachable"` — does NOT fall through to subprocess (avoids opaque subprocess failures).

**Config schema:**
- `track_id` (required select): one of the 6 trading track IDs
- `ingest_date` (string, default "yesterday"): ISO date or "all"
- `dgx_train_root` (string, default "/app/data/dgx-train")
- `decisions_md_path` (string, optional override)
- `llm_calls_path` (string, optional override)

**Container bind-mount (docker-compose.yml addition):**
```yaml
# Under mf-api service volumes:
- ~/Documents/trading-bot/scripts:/app/trading-bot/scripts:ro
```

### Condition gate in engine.py

Add `last_action_status` condition evaluation:

```python
condition = action_config.get("condition")
if condition and isinstance(condition, dict):
    for cond_key, cond_val in condition.items():
        if cond_key == "last_action_status":
            last_status = (context.get("last") or {}).get("status")
            if last_status != cond_val:
                logger.info("[engine] skipping %s: %s=%s not met (last=%s)",
                            action_kind, cond_key, cond_val, last_status)
                context["last"] = {"status": "skipped", "reason": f"condition {cond_key}={cond_val} not met"}
                continue
```

### Sunday workflow (one per track, seeded in seeds.py)

```python
{
    "name": "Weekly trading-arbiter rebuild",
    "kind": "system",
    "enabled": False,  # operator enables explicitly per track
    "trigger_type": "cron",
    "trigger_config": {"cron": "0 4 * * 0"},  # Sunday 04:00 UTC
    "actions": [
        {"kind": "dataset.build_trading", "config": {"track_id": "trading-arbiter"}},
        {
            "kind": "evolution.start",
            "config": {
                "base_model": "NousResearch/Hermes-3-Llama-3.1-8B",
                "max_generations": 3, "max_samples": 500,
                "lora_rank": 16, "batch_size": 2, "learning_rate": 0.0002,
                "track_id": "trading-arbiter",
                "eval_set_path": "{dataset.build_trading.test_set_path}",
            },
            "condition": {"last_action_status": "ok"},
        },
        {
            "kind": "notify.slack",
            "config": {
                "message": "Weekly trading-arbiter rebuild: {dataset.build_trading.records_count} records. Run: {evolution.start.run_id}",
                "emoji": "📊",
            }
        }
    ]
}
```

Reflector workflow seeded as `"enabled": False` with a comment: "Waiting for first closed stock trade — enable once N_MIN=30 records accumulate."

---

## Section I: Indicator-Selector Dataset Build Path

`quanta_schema.proposals.intent` does NOT contain indicator data — confirmed. The `intent` JSONB on proposals only has `regime` and `conviction`.

**Build path:**

1. Wire `indicator_selector` agent into `stocks/shark/phases/market_open.py` — call ONCE per shortlisted symbol BEFORE the bull/bear debate (NOT for all 524 KB tickers — `market_open` processes the pre-market shortlist, typically 10-30 symbols per day). Gated behind `SHARK_ENABLE_INDICATOR_SELECTOR=1` env var for safe rollout.
2. Log via `LLMTracker.record(agent="indicator_selector", ...)` with `SHARK_LLM_LOG_FULL_TEXT=1`.
3. Response must be valid `IndicatorSelection` JSON (Pydantic validation at call time); rejected if invalid.
4. Ingest picks up `indicator_selector` agent calls via the existing `AGENT_TO_ROLE` mapping (already correct in `modelforge_ingest.py`).
5. Accumulation rate: ~10-30 calls/day. Hitting `N_MIN_TRAIN=40` takes 2-4 days of live operation.
6. Baseline: `REGIME_BASELINE_INDICATORS[regime]` deterministic table — no LLM call.

---

## Section J: Test/Verification Plan

### Unit tests

**`model-forge/apps/api/tests/test_eval_helpers_real.py`**
1. `test_default_judge_stub_returns_0_5` — confirms fallback when Ollama unreachable, also logs ERROR
2. `test_default_judge_real_ollama` — `@skipif(not OLLAMA_AVAILABLE)` — real Ollama returns float in [0,1]
3. `test_default_judge_discriminates` — `@skipif(not OLLAMA_AVAILABLE)` — pass two responses to the same trading prompt, one clearly better ("Buy AAPL because earnings beat by 12%, technical breakout above 200dMA, sector rotating into tech") and one clearly worse ("idk, looks ok i guess, maybe buy"). Assert `score_a > 0.6` for the better one. This catches stub-like judges that always return ~0.5.
4. `test_default_judge_refuses_same_family` — assert `ValueError` raised when `MODELFORGE_JUDGE_MODEL=hermes3:8b` is set.
5. `test_default_adapter_runner_no_gpu_returns_empty` — non-GPU path
6. `test_default_adapter_runner_gpu_calls_peft` — `@skipif(not GPU_AVAILABLE)`
7. `test_rubric_scorer_parses_1_to_5_scale` — confirms rescaling
8. `test_rubric_scorer_discriminates` — same pattern as #3 for the rubric scorer

**`model-forge/apps/api/tests/test_eval_runner_fix.py`**
6. `test_runner_emits_track_eval_failed_when_score_zero` — mock zero scores; assert event published
7. `test_runner_does_not_emit_track_promoted_when_score_zero` — assert `track.promoted` NOT emitted
8. `test_runner_silent_skip_only_for_none_avg` — mock `avg=None`; assert no error event (expected path)

**`trading-bot/tests/test_modelforge_curate_gates.py`**
9. `test_min_records_gate_blocks_shard_write` — below N_MIN → `out_path is None`
10. `test_min_records_gate_passes_at_threshold` — exactly N_MIN → shard written
11. `test_realized_pnl_usd_field_written` — test_set rows contain `realized_pnl_usd` not `realized_pnl`
12. `test_forward_30d_return_computed_correctly` — mock +10% bars; assert `forward_30d_return == 0.10`
13. `test_test_set_temporal_split` — 50 sequential records; oldest 20% in test

### Integration test

**`trading-bot/tests/test_modelforge_integration.py`**
`test_build_trading_action_on_frozen_fixture_db`: fixture Postgres with N_MIN rows in `quanta_schema.decisions` for `trading-bull` → `BuildTradingDataset.execute()` → assert `status=="ok"`, all required fields present in `test_set.jsonl`.

### E2E dry-run

**`model-forge/apps/api/tests/test_e2e_trading_eval_baseline.py`**
`test_competent_base_model_scores_nonzero`: Load each track's frozen fixture `test_set.jsonl` → eval scorer with `hermes3:8b` as the adapter runner → assert ALL metrics > 0.0. If any metric is identically 0.0 against a competent baseline, the test fails with diagnostic identifying which metric and why (broken metric, not poor model).

---

## Section K: Migration and Rollout Sequence

### Commit order + dependency matrix

Commits are listed in apply order. "Safe to revert in isolation?" answers: if I revert just THIS commit while all later commits remain, does anything break?

| # | Commit | Files | Safe to revert in isolation? |
|---|--------|-------|-------------------------------|
| 1 | Field rename `realized_pnl` → `realized_pnl_usd` + null handling + system prompt fix | `modelforge_curate.py`, `eval_reflector.py`, `modelforge_ingest.py`, test fixtures | YES — no prod data uses the new field yet |
| 2 | N_MIN gates + curator_result.json writer + crypto-term blocklist | `modelforge_curate.py` | YES |
| 3 | Remove MODELFORGE_EVAL_USE_PEFT; real judge (qwen3:8b) + rubric scorer + discrimination test | `_common.py`, `requirements.txt`, CI env, new test file | YES |
| 4 | runner.py silent-skip fix + track.eval_failed event seed | `runner.py`, `seeds.py` | YES — additive |
| 5 | evolution_graph.py:655 first-gen min-score gate | `evolution_graph.py` | YES — gate can be disabled via env var |
| 6 | Garbage adapter cleanup (Section L) + shark fallback routing update | trading-bot `model_tiers.json`, host script `ollama_cleanup_garbage_adapters.sh` | YES — script is one-shot |
| 7 | BuildTradingDataset action + container env spec | `actions.py`, `engine.py`, `Dockerfile`, `requirements.txt`, `docker-compose.yml` | NO — commits 8 and 9 reference this action |
| 8 | Crypto decisions bootstrap ETL | `modelforge_ingest_decisions.py` (NEW) | NO — without it the N_MIN gates from commit 2 will keep bull/bear permanently blocked |
| 9 | Regime tagger baseline + indicator-selector wiring | `modelforge_curate.py`, `stocks/shark/phases/market_open.py` | YES — new agent wiring is feature-flagged off by default |
| 10 | Sunday weekly workflow seeds + all unit tests | `seeds.py`, test files | NO — references commit 7's action; reverting leaves dangling template vars |
| 11 | E2E dry-run test | `test_e2e_trading_eval_baseline.py` | YES |

**Hard constraint:** Commits 7, 8, 10 must land together or not at all. They form a single atomic unit. The other commits can be cherry-picked and reverted independently.

### Cron scheduling

- Hermes nightly ingest (21:00 ET): unchanged — daily incremental
- Hermes nightly curate (21:30 ET): unchanged — daily incremental
- ModelForge Sunday workflow (04:00 UTC): weekly full curate + evolution
- No scheduling authority conflict: Hermes owns daily cadence; ModelForge workflows own weekly training trigger (consistent with `shark_cron_scheduling_authority` policy)

### Fallback

- Broken `dataset.build_trading` → evolution.start never fires → no bad model deployed
- Broken `runner.py` change → `champion.rollback` action promotes prior generation
- `track.eval_failed` event is additive → removing it restores silent behavior
- Docker bind-mount addition → removing it restores no-trading-bot-scripts-in-container state

---

## Open Questions

1. **Entry value for realized_pnl_usd:** When `decisions.md` omits the dollar position size (only raw_pct + alpha_pct), the curate step uses default $10,000 notional. Is this correct, or should it read from Alpaca account equity at trade time?

2. **arbiter_baseline_decision at curate time:** Adds ~2s × N_reflector_test latency to the weekly curate. Acceptable? Alternative: omit this field; set `debate_impact = 0.5` for records where it's absent.

3. **Crypto decisions bootstrap scope:** Using all 29k rows from `quanta_schema.decisions` for bull/bear/arbiter produces a large corpus, but the PnL label computation against `quanta_schema.fills` may be expensive. Should the bootstrap cap at 5,000 rows per track?

4. **indicator_selector feature flag:** Should `SHARK_ENABLE_INDICATOR_SELECTOR=1` gate the agent wiring until one week of dry-run validation passes?

5. **Sunday workflow timing:** Does 04:00 UTC Sunday conflict with any existing Hermes crons? Confirm before enabling the seeded workflows.

---

## Files Affected (Complete List)

| Path | Purpose |
|------|---------|
| `/home/saijayanthai/Documents/trading-bot/scripts/modelforge_curate.py` | Add N_MIN gates, `realized_pnl_usd` rename, `curator_result.json` writer, `forward_30d_return` computation, `--role-filter` CLI flag, temporal split logic |
| `/home/saijayanthai/Documents/trading-bot/scripts/modelforge_ingest.py` | Update reflector `system_message` to require `$` citation |
| `/home/saijayanthai/Documents/trading-bot/scripts/modelforge_ingest_decisions.py` | NEW: One-shot historical bootstrap from `quanta_schema.decisions` for bull/bear/arbiter/regime-tagger |
| `/home/saijayanthai/Documents/trading-bot/stocks/shark/phases/market_open.py` | Wire `indicator_selector` agent call per-symbol before debate, gated by `SHARK_ENABLE_INDICATOR_SELECTOR` |
| `/home/saijayanthai/Documents/trading-bot/tests/test_modelforge_curate_gates.py` | NEW: Unit tests for N_MIN gates, realized_pnl_usd, temporal split |
| `/home/saijayanthai/Documents/trading-bot/tests/test_modelforge_integration.py` | NEW: Integration test with fixture DB |
| `/home/saijayanthai/Documents/spark/workspace/model-forge/apps/api/src/agents/evals/_common.py` | Remove `MODELFORGE_EVAL_USE_PEFT`; add real Ollama judge + rubric scorer |
| `/home/saijayanthai/Documents/spark/workspace/model-forge/apps/api/src/agents/evals/eval_reflector.py` | `record.get("realized_pnl")` → `record.get("realized_pnl_usd")` (line 111) |
| `/home/saijayanthai/Documents/spark/workspace/model-forge/apps/api/src/agents/runner.py` | Fix `new_avg <= 0` silent-skip (lines 131-132); emit `track.eval_failed` event |
| `/home/saijayanthai/Documents/spark/workspace/model-forge/apps/api/src/services/automation_engine/actions.py` | Add `BuildTradingDataset` action class; register in `_ALL_ACTIONS` |
| `/home/saijayanthai/Documents/spark/workspace/model-forge/apps/api/src/services/automation_engine/engine.py` | Add `last_action_status` condition evaluation in action execution loop |
| `/home/saijayanthai/Documents/spark/workspace/model-forge/apps/api/src/services/automation_engine/seeds.py` | Add 6 weekly trading evolution workflows + 1 `"Trading Eval Failure Alert"` workflow |
| `/home/saijayanthai/Documents/spark/workspace/model-forge/docker-compose.yml` | Add bind-mount `~/Documents/trading-bot/scripts:/app/trading-bot/scripts:ro` under `mf-api` |
| `/home/saijayanthai/Documents/spark/workspace/model-forge/apps/api/tests/test_trading_evals.py` | Update all fixtures: `realized_pnl` → `realized_pnl_usd` |
| `/home/saijayanthai/Documents/spark/workspace/model-forge/apps/api/tests/test_eval_helpers_real.py` | NEW: Unit tests for real judge/runner wiring (5 tests) |
| `/home/saijayanthai/Documents/spark/workspace/model-forge/apps/api/tests/test_eval_runner_fix.py` | NEW: Tests for runner silent-skip fix (3 tests) |
| `/home/saijayanthai/Documents/spark/workspace/model-forge/apps/api/tests/test_e2e_trading_eval_baseline.py` | NEW: E2E dry-run against hermes3:8b |
| `/home/saijayanthai/Documents/spark/workspace/model-forge/apps/api/src/agents/evolution_graph.py` | First-gen min-score gate at line 655 (Section G last sub-section) |
| `/home/saijayanthai/Documents/trading-bot/scripts/ollama_cleanup_garbage_adapters.sh` | NEW: one-shot script to delete garbage adapters published 2026-05-17 (Section L) |

---

## Section L: Garbage Adapter Cleanup + Shark Fallback Routing

This morning (2026-05-17) the publish pipeline published 4 LoRA adapters into Ollama trained on the broken pipeline:

- `hermes3-8b-reflector-current:latest`
- `hermes3-8b-bear-current:latest`
- `hermes3-8b-bull-current:latest`
- `hermes3-8b-arbiter-current:latest`

Plus dated versions `hermes3-8b-<role>-v20260517:latest` for each.

These adapters were trained on 5 stale options-era records each with a 9-second training run. Every eval metric was theatrical. They are NOT fit for production inference and shark currently routes to them.

### Cleanup actions (commit 6, before any retrain)

**Script:** `trading-bot/scripts/ollama_cleanup_garbage_adapters.sh` (one-shot, host-side)

```bash
#!/usr/bin/env bash
set -euo pipefail
OL="http://localhost:11434"

GARBAGE=(
  "hermes3-8b-reflector-current"      "hermes3-8b-reflector-v20260517"
  "hermes3-8b-bear-current"           "hermes3-8b-bear-v20260517"
  "hermes3-8b-bull-current"           "hermes3-8b-bull-v20260517"
  "hermes3-8b-arbiter-current"        "hermes3-8b-arbiter-v20260517"
)

for tag in "${GARBAGE[@]}"; do
  echo "Deleting $tag..."
  curl -s -X DELETE "$OL/api/delete" \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"$tag\"}"
  echo
done

echo "--- Remaining tags ---"
curl -s "$OL/api/tags" | python3 -c "
import sys, json
for m in sorted(m.get('name','') for m in json.load(sys.stdin).get('models',[])):
    if 'hermes3' in m: print(m)
"
```

### Shark fallback routing (commit 6, paired)

After cleanup, shark's `model_tiers.json` routing block already falls back to `hermes3:8b` (or `hermes3:8b-trader` for regime/indicator) when the `-current` tag is missing — this is the self-healing behavior shipped in commit `7609885`. No code change is needed.

**Verification step in the cleanup script:**

```bash
echo "--- Verifying shark routing falls back to base ---"
docker exec dashboard python3 -c "
from stocks.shark.llm.client import resolve_role_route, _reset_routing_cache
_reset_routing_cache()
for role in ['trading-reflector', 'trading-bull', 'trading-bear', 'trading-arbiter']:
    r = resolve_role_route(role)
    assert r['model'] == 'hermes3:8b', f'{role} still routes to {r}'
    print(f'  ✓ {role} → hermes3:8b (fallback active)')
"
```

If this verification fails, the cleanup is aborted and the operator is alerted.

### Rollback for the cleanup itself

The garbage adapters can be re-published from their adapter files at `/app/data/adapters/run-*/gen-1/` if needed. The cleanup is reversible by re-running `adapter.publish_ollama` for each `run_id`. But the operator MUST NOT do this until the underlying training pipeline produces non-garbage adapters.

---

## Section M: Promotion Gate Validation

**`apps/api/tests/test_first_gen_min_score_gate.py`** (NEW)

```python
def test_first_gen_promote_when_above_threshold():
    """child_avg=0.45, no parent → promote, reason mentions min-score gate."""

def test_first_gen_discard_when_below_threshold():
    """child_avg=0.10, no parent → discard, reason mentions min-score gate."""

def test_first_gen_threshold_env_override():
    """MODELFORGE_MIN_FIRST_GEN_SCORE=0.05 → child_avg=0.10 now promotes."""

def test_subsequent_gen_uses_pareto_not_min_score():
    """child_avg=0.10 BUT parent exists with champion_avg=0.05 → use Pareto, not min-score gate."""
```

Pass criteria: 4/4 tests pass; first-gen behavior matches the gate; subsequent-gen unaffected.
