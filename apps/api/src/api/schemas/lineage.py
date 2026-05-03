from pydantic import BaseModel


class LineageNodeSchema(BaseModel):
    id: str
    label: str
    generation: int
    promoted: bool
    scores: dict[str, float] = {}
    avg_score: float = 0.0
    is_champion: bool = False
    method: str | None = None
    decision_reason: str | None = None
    parent_id: str | None = None


class LineageEdge(BaseModel):
    source: str
    target: str
    promoted: bool = False


class LineageTree(BaseModel):
    nodes: list[LineageNodeSchema]
    edges: list[LineageEdge]
    total_nodes: int
    total_promoted: int
    total_discarded: int
    champion_id: str | None = None
