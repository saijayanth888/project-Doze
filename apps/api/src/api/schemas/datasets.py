"""Pydantic schemas for dataset management."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DatasetSummary(BaseModel):
    dataset_id: str
    generation: int | None = None
    num_samples: int = 0
    categories: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    size_mb: float = 0.0
    created_at: datetime | None = None
    kind: str = Field(description="curated|custom")


class DatasetList(BaseModel):
    datasets: list[DatasetSummary]
    total: int


class DatasetPreview(BaseModel):
    dataset_id: str
    kind: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    samples: list[dict[str, str]] = Field(default_factory=list)


class DatasetUploadResponse(BaseModel):
    dataset_id: str
    num_samples: int
    duplicates_skipped: int = 0
    message: str


class DatasetQuality(BaseModel):
    dataset_id: str
    duplicate_rate: float = 0.0
    avg_instruction_len: float = 0.0
    avg_response_len: float = 0.0
    length_histogram: dict[str, list[int]] = Field(
        default_factory=dict,
        description="bucket_edges and counts",
    )
    category_distribution: dict[str, float] = Field(default_factory=dict)
    overlap_with_training: int = 0
    embedding_diversity: float | None = None


class SavePairRequest(BaseModel):
    dataset_id: str
    instruction: str = Field(..., min_length=1, max_length=50000)
    response: str = Field(..., min_length=1, max_length=50000)


class SavePairResponse(BaseModel):
    ok: bool = True
    dataset_id: str
    appended: bool = True
