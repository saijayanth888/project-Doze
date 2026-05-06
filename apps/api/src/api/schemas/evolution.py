from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvolutionRequest(BaseModel):
    """POST body for `/api/evolve/start`. Presets may include extra keys — ignore them."""

    model_config = ConfigDict(extra="ignore")

    base_model: str = Field(default="llama3.2:3b", description="Base Ollama model tag")
    existing_adapter: str | None = Field(default=None, description="Path to existing LoRA adapter")
    max_generations: int = Field(default=10, ge=1, le=100)
    lora_rank: int = Field(default=16, ge=4, le=64)
    lora_alpha: int = Field(default=32, ge=8, le=128)
    learning_rate: float = Field(default=2e-4, ge=1e-5, le=1e-2)
    batch_size: int = Field(default=2, ge=1, le=16)
    custom_dataset_id: str | None = Field(
        default=None,
        description="Uploaded custom dataset id under data/custom/",
    )
    max_samples: int | None = Field(
        default=None,
        ge=100,
        le=100000,
        description="Override curation sample budget (maps to curator max_samples)",
    )


class EvolutionStatus(BaseModel):
    run_id: str
    status: str = Field(
        description="starting|running|evaluating|training|comparing|completed|failed"
    )
    generation: int = 0
    current_step: str | None = None
    started_at: datetime | None = None
    elapsed_seconds: float | None = None
    error: str | None = None
    config: dict[str, Any] = {}


class EvolutionPollStatus(BaseModel):
    """Latest / active run for dashboard polling (`GET /api/evolve/status`)."""

    run_id: str | None = None
    status: str = "idle"
    is_running: bool = False
    generation: int = 0
    current_step: str | None = None
    started_at: datetime | None = None
    elapsed_seconds: float | None = None
    error: str | None = None
    config: dict[str, Any] = {}


class EvolutionEvent(BaseModel):
    event_type: str = Field(description="generation_complete|champion_promoted|run_complete|error")
    run_id: str
    generation: int
    data: dict[str, Any] = {}
    timestamp: datetime


class EvolutionStopResponse(BaseModel):
    run_id: str
    stopped: bool
    message: str
