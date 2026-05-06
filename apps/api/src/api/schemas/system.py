from typing import Any

from pydantic import BaseModel, Field


class HealthCheck(BaseModel):
    status: str
    version: str = "0.1.0"
    environment: str
    postgres: str
    redis: str
    ollama: str


class GPUStatus(BaseModel):
    gpu_available: bool
    device: str
    cuda_available: bool
    vram_total_gb: float | None = None
    vram_used_gb: float | None = None
    util_percent: float | None = None
    temp_celsius: float | None = None
    gpu_name: str | None = None
    note: str | None = None
    inference_note: str | None = None
    ollama_inference_ok: bool = False


class EnvironmentInfo(BaseModel):
    environment: str
    python_version: str
    platform: str
    gpu_available: bool
    ollama_host: str
    db_host: str
    features: dict[str, bool]


class N8nAlertIn(BaseModel):
    """Inbound alert payload from n8n HTTP Request nodes."""

    alert_type: str = Field(default="unknown")
    failed_services: str | None = None
    http_status_code: str | int | None = None
    api_status: str | None = None
    postgres_status: str | None = None
    redis_status: str | None = None
    severity: str | None = None
    detected_at: str | None = None
    extra: dict[str, Any] | None = None
