from pydantic import BaseModel


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


class EnvironmentInfo(BaseModel):
    environment: str
    python_version: str
    platform: str
    gpu_available: bool
    ollama_host: str
    db_host: str
    features: dict[str, bool]
