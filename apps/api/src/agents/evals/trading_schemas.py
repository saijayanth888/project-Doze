"""Pydantic schemas duplicated from trading-bot.

These are the canonical shapes the trading-bot LLM roles produce. They live
here so model-forge can validate adapter outputs without importing from
trading-bot at runtime -- ModelForge is a standalone repo. Keep these
roughly in sync with trading-bot's authoritative copies under
``stocks/memory/`` and ``stocks/shark/llm/schemas/``.

Future cleanup: extract into a tiny shared ``trading-protocols`` package and
depend on it from both repos. Documented in ``TRADING_EVALS_HANDOFF.md``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


# -- Arbiter / Portfolio Manager ----------------------------------------
class TraderProposal(BaseModel):
    """Structured output from the trading-arbiter role.

    The PM emits one of these per debate. Trading-bot's risk_manager then
    sizes the position; if validation fails the call is aborted and the
    debate is logged as ``schema_violation``.
    """

    action: Literal["buy", "sell", "hold", "close"] = Field(
        ..., description="Recommended next action for the ticker."
    )
    ticker: str = Field(..., min_length=1, max_length=10)
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str = Field(..., min_length=10, max_length=2000)
    horizon_days: int = Field(..., ge=1, le=365)
    stop_loss_pct: float | None = Field(None, ge=0.0, le=1.0)
    take_profit_pct: float | None = Field(None, ge=0.0, le=10.0)

    @field_validator("ticker")
    @classmethod
    def _upper_ticker(cls, v: str) -> str:
        return v.strip().upper()


# -- Regime tagger ------------------------------------------------------
RegimeLabel = Literal[
    "trending_up",
    "trending_down",
    "ranging",
    "high_volatility",
    "low_volatility",
    "breakout_up",
    "breakout_down",
]


class RegimeTag(BaseModel):
    """Structured output from the trading-regime-tagger role.

    Per-symbol, per-day classification. Consumed by Shark's indicator pipeline
    to pick an appropriate strategy template.
    """

    symbol: str = Field(..., min_length=1, max_length=12)
    regime: RegimeLabel
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = Field(..., min_length=5, max_length=500)
    timestamp: str = Field(..., description="ISO 8601 date or datetime")

    @field_validator("symbol")
    @classmethod
    def _upper_symbol(cls, v: str) -> str:
        return v.strip().upper()


# -- Indicator selector -------------------------------------------------
# Whitelist mirrors trading-bot's freqtrade strategy library. Keep in
# alphabetical groups for diff-friendliness.
_KNOWN_INDICATORS = frozenset({
    "adx", "atr", "bbands", "cci", "ema", "kama", "macd", "mfi",
    "obv", "roc", "rsi", "sar", "sma", "stoch", "tema", "vwap",
    "williams_r", "supertrend", "ichimoku", "donchian",
})


class IndicatorSelection(BaseModel):
    """Structured output from the trading-indicator-selector role.

    Returns at most 8 indicators picked from the freqtrade-known set. The
    downstream backtester uses exactly this subset; anything not in the
    whitelist or beyond 8 is rejected.
    """

    symbol: str = Field(..., min_length=1, max_length=12)
    regime: RegimeLabel
    indicators: list[str] = Field(..., min_length=1, max_length=8)
    rationale: str = Field(..., min_length=5, max_length=500)

    @field_validator("symbol")
    @classmethod
    def _upper_symbol(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("indicators")
    @classmethod
    def _check_known(cls, v: list[str]) -> list[str]:
        normalized = [i.strip().lower() for i in v]
        unknown = [i for i in normalized if i not in _KNOWN_INDICATORS]
        if unknown:
            raise ValueError(
                f"unknown indicators (not in freqtrade whitelist): {unknown}"
            )
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate indicators")
        return normalized


__all__ = [
    "TraderProposal",
    "RegimeTag",
    "RegimeLabel",
    "IndicatorSelection",
]
