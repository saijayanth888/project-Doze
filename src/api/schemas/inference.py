from pydantic import BaseModel, Field


class InferenceRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=10000)
    model_id: str | None = Field(default=None, description="Ollama model tag, e.g. llama3.2:3b")
    max_tokens: int = Field(default=256, ge=1, le=4096)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class InferenceResponse(BaseModel):
    response: str
    model: str
    tokens: int | None = None
    latency_ms: float | None = None
    source: str = "ollama"


class CompareRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=10000)
    model_a: str = Field(default="llama3.2:3b", description="Base model tag")
    model_b: str = Field(default="llama3.2:3b", description="Champion model tag")
    max_tokens: int = Field(default=256, ge=1, le=4096)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class CompareResponse(BaseModel):
    prompt: str
    base: InferenceResponse
    champion: InferenceResponse
