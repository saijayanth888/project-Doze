"""Tests for the trading-eval modules.

Covers:

* Each scoring module: mock adapter + test set on disk, run, assert score keys
  + ranges.
* Registry dispatch: each track_id resolves to the right callable and the
  returned EvalResult carries the expected keys.
* Pareto tiebreaker: when ``faithfulness_regex`` ticks up but
  ``predictive_hit_rate_30d`` regresses >5%, ``check_tiebreaker`` flags
  rollback.
* Schemas: the duplicated Pydantic schemas accept canonical shapes and
  reject obviously malformed ones.

No GPU / no torch / no peft -- the adapter runner is injected.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.eval_backend import EvalResult
from agents.evals import (
    eval_arbiter,
    eval_debater,
    eval_reflector,
    eval_structured_json,
)
from agents.evals.eval_registry import (
    EVAL_REGISTRY,
    list_track_ids,
    resolve_eval,
    run_for_track,
)
from agents.evals.trading_schemas import (
    IndicatorSelection,
    RegimeTag,
    TraderProposal,
)
from config.trading_eval_weights import (
    DEFAULT_ROLLBACK_THRESHOLD_PCT,
    PARETO_TIEBREAKER_PRIORITY,
    check_tiebreaker,
    get_rollback_threshold,
    get_tiebreaker_metric,
)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _write_jsonl(path: Path, records: list[dict]) -> None:
    """Write one JSON record per line so :func:`load_test_set` can consume."""
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _make_runner(responses: list[str]):
    """Adapter-runner stub: returns ``responses`` truncated/padded to match prompts."""
    def runner(_adapter_path: str, prompts: list[str]) -> list[str]:
        out: list[str] = []
        for i, _ in enumerate(prompts):
            out.append(responses[i] if i < len(responses) else "")
        return out
    return runner


# ---------------------------------------------------------------------
# trading-reflector
# ---------------------------------------------------------------------
def test_reflector_returns_all_four_keys(tmp_path):
    """All four documented keys are present in the EvalResult.scores dict."""
    test_set = tmp_path / "reflector.jsonl"
    _write_jsonl(test_set, [
        {
            "prompt": "Summarize trade AAPL closed at +$42.5 alpha.",
            "realized_pnl_usd": 42.5,
            "forward_30d_return": 0.034,
            "predicted_direction": "long",
            "arbiter_prompt": "Should we re-enter AAPL?",
            "arbiter_baseline_decision": "hold",
        },
        {
            "prompt": "Summarize trade TSLA closed at -$120.0 loss.",
            "realized_pnl_usd": -120.0,
            "forward_30d_return": -0.07,
            "predicted_direction": "short",
            "arbiter_prompt": "Should we re-enter TSLA?",
            "arbiter_baseline_decision": "buy",
        },
    ])

    responses = [
        "We closed AAPL at +$42.5 alpha; bullish continuation likely.",
        "We closed TSLA at -$120.0; downside risk persists, bearish.",
    ]
    arbiter_responses = ["buy", "hold"]  # different from baseline -> high debate_impact

    result = eval_reflector.score(
        adapter_path="mock-adapter",
        test_set_path=str(test_set),
        adapter_runner=_make_runner(responses),
        arbiter_adapter_path="mock-arbiter",
        arbiter_runner=_make_runner(arbiter_responses),
    )

    assert isinstance(result, EvalResult)
    expected_keys = {
        "faithfulness_regex",
        "judge_score",
        "debate_impact",
        "predictive_hit_rate_30d",
    }
    assert set(result.scores.keys()) == expected_keys
    for k, v in result.scores.items():
        assert 0.0 <= v <= 1.0, f"{k}={v} out of [0,1]"

    # Both responses cited the exact alpha figure -> 100% faithfulness.
    assert result.scores["faithfulness_regex"] == pytest.approx(1.0)
    # Both predicted directions matched realized direction -> 100% hit-rate.
    assert result.scores["predictive_hit_rate_30d"] == pytest.approx(1.0)


def test_reflector_handles_empty_test_set(tmp_path):
    """Missing test set returns zeros, not a crash."""
    result = eval_reflector.score(
        adapter_path="x",
        test_set_path=str(tmp_path / "missing.jsonl"),
        adapter_runner=_make_runner([]),
    )
    assert result.scores == {
        "faithfulness_regex": 0.0,
        "judge_score": 0.0,
        "debate_impact": 0.0,
        "predictive_hit_rate_30d": 0.0,
    }


# ---------------------------------------------------------------------
# trading-bull / trading-bear
# ---------------------------------------------------------------------
@pytest.mark.parametrize("role", ["bull", "bear"])
def test_debater_keys_and_ranges(tmp_path, role):
    test_set = tmp_path / f"{role}.jsonl"
    _write_jsonl(test_set, [
        {
            "prompt": "Pitch AAPL at $182.50.",
            "opponent_strongest_point": "RSI oversold at 22",
            "prior_response": "AAPL going up.",
        },
        {
            "prompt": "Pitch NVDA at $890.10.",
            "opponent_strongest_point": "Q3 revenue miss",
            "prior_response": "NVDA going up.",
        },
    ])

    responses = [
        # Dense evidence + names the opponent's RSI point.
        "AAPL at $182.50 is a buy; RSI at 22 is oversold, MACD bullish, +3.2% from 50-day EMA on 2026-05-10.",
        "NVDA at $890.10 even after Q3 revenue miss; ATR -1.5%, MACD turning, 2026-05-09 breakout above $880.",
    ]

    def judge(_prompt, _a, _b):
        return 0.7  # child preferred 70% of the time

    result = eval_debater.score(
        adapter_path="mock",
        test_set_path=str(test_set),
        role=role,
        adapter_runner=_make_runner(responses),
        judge=judge,
    )
    expected_keys = {"evidence_density", "opponent_acknowledgment_rate", "judge_preference"}
    assert set(result.scores.keys()) == expected_keys
    for k, v in result.scores.items():
        assert 0.0 <= v <= 1.0, f"{k}={v} out of [0,1]"

    # Both responses named the opponent's claim -> 100%.
    assert result.scores["opponent_acknowledgment_rate"] == pytest.approx(1.0)
    # Judge always returned 0.7.
    assert result.scores["judge_preference"] == pytest.approx(0.7)


def test_debater_rejects_invalid_role(tmp_path):
    test_set = tmp_path / "x.jsonl"
    _write_jsonl(test_set, [{"prompt": "x"}])
    with pytest.raises(ValueError):
        eval_debater.score(
            adapter_path="x",
            test_set_path=str(test_set),
            role="neutral",  # type: ignore[arg-type]
            adapter_runner=_make_runner(["x"]),
        )


# ---------------------------------------------------------------------
# trading-arbiter
# ---------------------------------------------------------------------
def _valid_proposal_json(action: str = "buy", ticker: str = "AAPL", pnl_horizon: int = 5) -> str:
    return json.dumps({
        "action": action,
        "ticker": ticker,
        "confidence": 0.75,
        "rationale": "Strong technicals plus fundamental tailwind from the quarter.",
        "horizon_days": pnl_horizon,
        "stop_loss_pct": 0.05,
        "take_profit_pct": 0.15,
    })


def test_arbiter_keys_and_validity_rate(tmp_path):
    test_set = tmp_path / "arbiter.jsonl"
    _write_jsonl(test_set, [
        {"prompt": "Decide for AAPL", "forward_5d_pnl_usd": 1500.0},
        {"prompt": "Decide for TSLA", "forward_5d_pnl_usd": -800.0},
        {"prompt": "Decide for NVDA", "forward_5d_pnl_usd": 200.0},
    ])

    responses = [
        _valid_proposal_json("buy", "AAPL"),
        "this is not json at all",  # parse failure
        _valid_proposal_json("buy", "NVDA"),
    ]

    result = eval_arbiter.score(
        adapter_path="mock",
        test_set_path=str(test_set),
        adapter_runner=_make_runner(responses),
        consistency_n=1,  # skip extra calls for speed
    )

    expected_keys = {
        "structured_output_validity_rate",
        "decision_consistency",
        "downstream_pnl_per_decision",
    }
    assert set(result.scores.keys()) == expected_keys
    for k, v in result.scores.items():
        assert 0.0 <= v <= 1.0, f"{k}={v} out of [0,1]"

    # 2 of 3 parsed validly -> 2/3.
    assert result.scores["structured_output_validity_rate"] == pytest.approx(2 / 3)
    # consistency_n=1 -> every valid record counts as consistent.
    assert result.scores["decision_consistency"] == pytest.approx(1.0)


def test_arbiter_consistency_detects_drift(tmp_path):
    """When the same prompt yields different tickers, consistency drops."""
    test_set = tmp_path / "arbiter_consistency.jsonl"
    _write_jsonl(test_set, [{"prompt": "Decide", "forward_5d_pnl_usd": 0.0}])

    call_count = {"n": 0}

    def stateful_runner(_adapter_path: str, prompts: list[str]) -> list[str]:
        out = []
        for _ in prompts:
            # Alternate ticker on each call -> consistency fails.
            ticker = "AAPL" if call_count["n"] % 2 == 0 else "TSLA"
            call_count["n"] += 1
            out.append(_valid_proposal_json("buy", ticker))
        return out

    result = eval_arbiter.score(
        adapter_path="mock",
        test_set_path=str(test_set),
        adapter_runner=stateful_runner,
        consistency_n=3,
    )
    assert result.scores["decision_consistency"] == pytest.approx(0.0)


def test_arbiter_pnl_sigmoid_in_range():
    """The internal sigmoid maps any PnL to [0, 1]."""
    from agents.evals.eval_arbiter import _pnl_to_score
    for pnl in (-1_000_000.0, -500.0, 0.0, 500.0, 1_000_000.0):
        v = _pnl_to_score(pnl)
        assert 0.0 <= v <= 1.0
    assert _pnl_to_score(0.0) == pytest.approx(0.5)
    assert _pnl_to_score(1000.0) > 0.5
    assert _pnl_to_score(-1000.0) < 0.5


# ---------------------------------------------------------------------
# trading-regime-tagger / trading-indicator-selector (structured JSON)
# ---------------------------------------------------------------------
def test_regime_tagger_validity_and_agreement(tmp_path):
    test_set = tmp_path / "regime.jsonl"
    _write_jsonl(test_set, [
        {
            "prompt": "Classify AAPL today",
            "baseline_output": {"regime": "trending_up"},
        },
        {
            "prompt": "Classify TSLA today",
            "baseline_output": {"regime": "ranging"},
        },
    ])
    responses = [
        json.dumps({
            "symbol": "AAPL",
            "regime": "trending_up",
            "confidence": 0.8,
            "reasoning": "Above 200-day EMA, ADX 28.",
            "timestamp": "2026-05-11",
        }),
        json.dumps({
            "symbol": "TSLA",
            "regime": "high_volatility",  # disagrees with baseline
            "confidence": 0.6,
            "reasoning": "ATR up sharply.",
            "timestamp": "2026-05-11",
        }),
    ]

    result = eval_structured_json.score(
        adapter_path="mock",
        test_set_path=str(test_set),
        schema=RegimeTag,
        adapter_runner=_make_runner(responses),
    )
    assert set(result.scores.keys()) == {
        "structured_output_validity_rate",
        "agreement_with_baseline",
    }
    # Both parsed.
    assert result.scores["structured_output_validity_rate"] == pytest.approx(1.0)
    # One agreed, one didn't -> 0.5.
    assert result.scores["agreement_with_baseline"] == pytest.approx(0.5)


def test_indicator_selector_jaccard_agreement(tmp_path):
    test_set = tmp_path / "indicator.jsonl"
    _write_jsonl(test_set, [
        {
            "prompt": "Pick indicators for AAPL trending_up",
            "baseline_output": {"indicators": ["ema", "macd", "rsi", "atr"]},
        },
    ])
    responses = [
        json.dumps({
            "symbol": "AAPL",
            "regime": "trending_up",
            # 3 of 4 baseline indicators present -> jaccard 3/5 = 0.6 >= 0.5.
            "indicators": ["EMA", "MACD", "RSI", "BBANDS"],
            "rationale": "Standard trend pack with volatility envelope.",
        }),
    ]
    result = eval_structured_json.score(
        adapter_path="mock",
        test_set_path=str(test_set),
        schema=IndicatorSelection,
        adapter_runner=_make_runner(responses),
    )
    assert result.scores["structured_output_validity_rate"] == pytest.approx(1.0)
    assert result.scores["agreement_with_baseline"] == pytest.approx(1.0)


def test_indicator_selector_rejects_unknown_indicators(tmp_path):
    test_set = tmp_path / "indicator_bad.jsonl"
    _write_jsonl(test_set, [
        {
            "prompt": "Pick indicators",
            "baseline_output": {"indicators": ["ema"]},
        },
    ])
    responses = [
        json.dumps({
            "symbol": "AAPL",
            "regime": "trending_up",
            "indicators": ["totally-made-up-indicator"],
            "rationale": "Should fail schema validation.",
        }),
    ]
    result = eval_structured_json.score(
        adapter_path="mock",
        test_set_path=str(test_set),
        schema=IndicatorSelection,
        adapter_runner=_make_runner(responses),
    )
    # The schema rejects the unknown indicator -> validity 0.
    assert result.scores["structured_output_validity_rate"] == pytest.approx(0.0)
    assert result.scores["agreement_with_baseline"] == pytest.approx(0.0)


# ---------------------------------------------------------------------
# Registry dispatch
# ---------------------------------------------------------------------
def test_registry_has_all_six_track_ids():
    expected = {
        "trading-reflector",
        "trading-bull",
        "trading-bear",
        "trading-arbiter",
        "trading-regime-tagger",
        "trading-indicator-selector",
    }
    assert set(EVAL_REGISTRY.keys()) == expected
    assert set(list_track_ids()) == expected


def test_registry_resolve_returns_none_for_unknown_track():
    assert resolve_eval("not-a-track") is None
    assert resolve_eval(None) is None
    assert resolve_eval("") is None
    assert resolve_eval("trading-reflector") is not None


def test_registry_dispatch_to_each_module(tmp_path):
    """Each registry key, when invoked, returns an EvalResult with non-empty scores."""
    # Build the smallest test set that satisfies every scorer simultaneously.
    test_set = tmp_path / "smoke.jsonl"
    _write_jsonl(test_set, [
        {
            "prompt": "Sample prompt",
            "realized_pnl_usd": 10.0,
            "forward_30d_return": 0.01,
            "forward_5d_pnl_usd": 100.0,
            "opponent_strongest_point": "RSI 22",
            "prior_response": "weak prior",
            "baseline_output": {"regime": "trending_up", "indicators": ["ema", "rsi"]},
        },
    ])
    # One reusable adapter response that's valid JSON for the JSON scorers
    # and also passes the prose checks.
    structured_resp = json.dumps({
        "symbol": "AAPL",
        "regime": "trending_up",
        "confidence": 0.7,
        "reasoning": "Test.",
        "timestamp": "2026-05-11",
        "indicators": ["ema", "rsi"],
        "rationale": "Test rationale.",
        "action": "buy",
        "ticker": "AAPL",
        "horizon_days": 5,
    })
    runner = _make_runner([structured_resp])

    for track_id in list_track_ids():
        # consistency_n keeps arbiter test cheap; all other modules ignore it.
        if track_id == "trading-arbiter":
            result = run_for_track(track_id, "mock-adapter", str(test_set),
                                   adapter_runner=runner, consistency_n=1)
        else:
            result = run_for_track(track_id, "mock-adapter", str(test_set),
                                   adapter_runner=runner)
        assert isinstance(result, EvalResult)
        assert len(result.scores) > 0, f"{track_id} returned empty scores"
        for k, v in result.scores.items():
            assert 0.0 <= v <= 1.0, f"{track_id}.{k}={v} out of [0,1]"


def test_registry_run_for_unknown_raises():
    with pytest.raises(KeyError):
        run_for_track("not-a-track", "x", "y")


# ---------------------------------------------------------------------
# Pareto tiebreaker
# ---------------------------------------------------------------------
def test_tiebreaker_priority_map_covers_all_tracks():
    """Every track in the registry has a Pareto tiebreaker metric."""
    for track_id in EVAL_REGISTRY:
        assert track_id in PARETO_TIEBREAKER_PRIORITY
        assert isinstance(PARETO_TIEBREAKER_PRIORITY[track_id], str)


def test_tiebreaker_flags_rollback_when_priority_metric_regresses():
    """Faithfulness up, predictive hit-rate down >5% -> rollback flagged."""
    parent = {"faithfulness_regex": 0.80, "predictive_hit_rate_30d": 0.65}
    child = {"faithfulness_regex": 0.95, "predictive_hit_rate_30d": 0.60}  # -7.7%
    report = check_tiebreaker("trading-reflector", parent, child)
    assert report["rollback"] is True
    assert report["metric"] == "predictive_hit_rate_30d"
    assert report["parent"] == pytest.approx(0.65)
    assert report["child"] == pytest.approx(0.60)
    assert report["delta_pct"] < 0
    assert "predictive_hit_rate_30d" in report["reason"]


def test_tiebreaker_passes_when_priority_metric_holds():
    """Hit-rate flat, faithfulness improves -> tiebreaker does not veto."""
    parent = {"faithfulness_regex": 0.80, "predictive_hit_rate_30d": 0.65}
    child = {"faithfulness_regex": 0.90, "predictive_hit_rate_30d": 0.66}
    report = check_tiebreaker("trading-reflector", parent, child)
    assert report["rollback"] is False
    assert "within tolerance" in report["reason"]


def test_tiebreaker_skips_when_metric_missing():
    """Missing parent or child value -> no veto."""
    report = check_tiebreaker("trading-reflector", {"faithfulness_regex": 0.8}, {})
    assert report["rollback"] is False
    assert "missing" in report["reason"]


def test_tiebreaker_unknown_track_is_noop():
    report = check_tiebreaker("mmlu-track", {"acc": 0.5}, {"acc": 0.3})
    assert report["rollback"] is False
    assert report["metric"] is None


def test_tiebreaker_arbiter_uses_pnl_metric_with_tighter_threshold():
    """Arbiter has a tighter threshold (3% per config)."""
    assert get_tiebreaker_metric("trading-arbiter") == "downstream_pnl_per_decision"
    assert get_rollback_threshold("trading-arbiter") < DEFAULT_ROLLBACK_THRESHOLD_PCT


def test_tiebreaker_zero_parent_uses_absolute_delta():
    """Division-by-zero guard: when parent is ~0, fall back to absolute delta."""
    parent = {"predictive_hit_rate_30d": 0.0}
    child = {"predictive_hit_rate_30d": -0.10}
    report = check_tiebreaker("trading-reflector", parent, child)
    assert report["rollback"] is True


# ---------------------------------------------------------------------
# Schema duplicates
# ---------------------------------------------------------------------
def test_trader_proposal_accepts_canonical_shape():
    p = TraderProposal.model_validate_json(_valid_proposal_json())
    assert p.action == "buy"
    assert p.ticker == "AAPL"
    assert 0.0 <= p.confidence <= 1.0


def test_trader_proposal_rejects_bad_action():
    bad = json.dumps({
        "action": "yolo",
        "ticker": "AAPL",
        "confidence": 0.5,
        "rationale": "x" * 20,
        "horizon_days": 5,
    })
    with pytest.raises(Exception):
        TraderProposal.model_validate_json(bad)


def test_regime_tag_normalizes_symbol():
    rt = RegimeTag(
        symbol="aapl",
        regime="trending_up",
        confidence=0.7,
        reasoning="test reasoning",
        timestamp="2026-05-11",
    )
    assert rt.symbol == "AAPL"


def test_indicator_selection_caps_at_eight():
    too_many = ["ema", "rsi", "macd", "atr", "bbands", "adx", "obv", "stoch", "cci"]
    with pytest.raises(Exception):
        IndicatorSelection(
            symbol="AAPL",
            regime="trending_up",
            indicators=too_many,
            rationale="too many",
        )


# ---------------------------------------------------------------------
# Module-level alias contract (for spec compatibility)
# ---------------------------------------------------------------------
def test_modules_expose_scorer_alias():
    """The spec calls for ``eval_reflector.eval`` etc. -- alias must exist.

    We bind it via ``globals()`` in each module to avoid shadowing Python's
    builtin name at the source level.
    """
    for mod in (eval_reflector, eval_debater, eval_arbiter, eval_structured_json):
        alias_attr = "eval"  # the spec-required attribute name
        assert hasattr(mod, alias_attr), f"{mod.__name__} missing {alias_attr!r} alias"
        assert callable(getattr(mod, alias_attr))
        # The alias must point at the same underlying score function so the
        # registry's references stay consistent with direct attribute access.
        assert getattr(mod, alias_attr) is mod._score_alias
