from fastapi import APIRouter

from api.routes import evaluation, evolution, inference, lineage, models, system, websocket

api_router = APIRouter()
api_router.include_router(evolution.router, prefix="/evolve", tags=["Evolution"])
api_router.include_router(models.router, prefix="/models", tags=["Models"])
api_router.include_router(lineage.router, prefix="/lineage", tags=["Lineage"])
api_router.include_router(evaluation.router, prefix="/eval", tags=["Evaluation"])
api_router.include_router(inference.router, prefix="/infer", tags=["Inference"])
api_router.include_router(system.router, prefix="/system", tags=["System"])
api_router.include_router(websocket.router, tags=["WebSocket"])
