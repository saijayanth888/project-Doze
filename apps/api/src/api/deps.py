from fastapi import Request

from config.database import get_pool
from config.settings import settings
from services.lineage_db import LineageDB
from services.model_registry import ModelRegistry
from services.ollama_client import OllamaClient


async def get_db(request: Request) -> LineageDB:
    pool = await get_pool()
    return LineageDB(pool=pool)


async def get_ollama() -> OllamaClient:
    return OllamaClient(host=settings.ollama_host)


async def get_registry() -> ModelRegistry:
    return ModelRegistry()
