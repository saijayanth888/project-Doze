from datetime import datetime

from pydantic import BaseModel


class ScoreMap(BaseModel):
    mmlu: float = 0.0
    arc_challenge: float = 0.0
    hellaswag: float = 0.0
    gsm8k: float = 0.0
    humaneval: float = 0.0


class ModelInfo(BaseModel):
    id: str
    base_model: str
    adapter_path: str | None = None
    generation: int = 0
    scores: dict[str, float] = {}
    promoted: bool = False
    created_at: datetime | None = None


class ChampionInfo(BaseModel):
    generation: int
    base_model: str
    adapter_path: str | None = None
    scores: dict[str, float] = {}
    avg_score: float = 0.0
    method: str | None = None
    promoted_at: datetime | None = None


class GenerationInfo(BaseModel):
    generation: int
    run_id: str | None = None
    promoted: bool
    parent_scores: dict[str, float] = {}
    child_scores: dict[str, float] = {}
    decision_reason: str | None = None
    method: str | None = None
    training_data_size: int = 0
    duration_seconds: float = 0.0
    created_at: datetime | None = None


class ModelList(BaseModel):
    total: int
    models: list[ModelInfo]
