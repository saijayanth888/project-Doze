"""Pydantic schemas for adapter management."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AdapterInfo(BaseModel):
    adapter_id: str
    run_id: str
    generation: int
    base_model: str
    scores: dict[str, float] | None = None
    size_mb: float = 0.0
    created_at: datetime | None = None
    is_champion: bool = False
    promoted: bool = False
    training_config: dict[str, Any] = Field(default_factory=dict)
    weak_categories: list[str] = Field(default_factory=list)
    adapter_path: str | None = None
    archived: bool = False
    status: str = Field(description="champion|promoted|discarded|archived")


class AdapterList(BaseModel):
    adapters: list[AdapterInfo]
    total: int
    champion_id: str | None = None
    total_disk_mb: float = 0.0


class RollbackResponse(BaseModel):
    previous_champion: str | None = None
    new_champion: str
    rolled_back: bool = True
    message: str


class ServeAdapterResponse(BaseModel):
    adapter_id: str
    mode: str = Field(description="ollama|vllm_hint")
    ollama_model: str | None = None
    message: str
    vllm_lora_path: str | None = None


class AdapterCompareInference(BaseModel):
    adapter_id: str
    response: str | None = None
    model: str | None = None
    tokens: int | None = None
    latency_ms: float | None = None
    source: str = "ollama"


class AdapterCompareResponse(BaseModel):
    adapter_a: AdapterInfo
    adapter_b: AdapterInfo
    inference_a: AdapterCompareInference | None = None
    inference_b: AdapterCompareInference | None = None


class CleanupResponse(BaseModel):
    deleted_count: int
    reclaimed_mb: float
    adapter_ids: list[str]
