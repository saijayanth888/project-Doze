from pydantic import BaseModel


class BenchmarkInfo(BaseModel):
    key: str
    label: str
    description: str
    weight: float


class ScoreTrend(BaseModel):
    generation: int
    benchmark: str
    parent_score: float
    child_score: float
    delta: float
    promoted: bool


class BenchmarkResult(BaseModel):
    generation: int
    scores: dict[str, float]
    avg_score: float
    promoted: bool


class ScoresResponse(BaseModel):
    total_datapoints: int
    generations: int
    benchmarks: int
    trends: list[ScoreTrend]


class BenchmarksResponse(BaseModel):
    total: int
    benchmarks: list[BenchmarkInfo]
