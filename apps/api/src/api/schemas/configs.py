"""Evolution preset schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PresetSummary(BaseModel):
    name: str
    is_builtin: bool = False
    created_at: datetime | None = None


class PresetList(BaseModel):
    presets: list[PresetSummary]
    total: int


class PresetDetail(BaseModel):
    name: str
    is_builtin: bool = False
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class SavePresetRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    config: dict[str, Any] = Field(default_factory=dict)
