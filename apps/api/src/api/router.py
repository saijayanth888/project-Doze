from fastapi import APIRouter

from api.routes import (
    adapters,
    automation,
    configs,
    datasets,
    ept,
    evaluation,
    evolution,
    experiments,
    exports,
    forge,
    history,
    inference,
    lineage,
    models,
    schedule,
    system,
    websocket,
    workflows,
)

api_router = APIRouter()
api_router.include_router(evolution.router, prefix="/evolve", tags=["Evolution"])
api_router.include_router(models.router, prefix="/models", tags=["Models"])
api_router.include_router(lineage.router, prefix="/lineage", tags=["Lineage"])
api_router.include_router(evaluation.router, prefix="/eval", tags=["Evaluation"])
api_router.include_router(inference.router, prefix="/infer", tags=["Inference"])
api_router.include_router(adapters.router, prefix="/adapters", tags=["Adapters"])
api_router.include_router(datasets.router, prefix="/datasets", tags=["Datasets"])
api_router.include_router(configs.router, prefix="/configs", tags=["Configs"])
api_router.include_router(system.router, prefix="/system", tags=["System"])
api_router.include_router(automation.router, prefix="/automation", tags=["Automation"])
api_router.include_router(workflows.router, prefix="/automation", tags=["Automation/Workflows"])
api_router.include_router(experiments.router, prefix="/experiments", tags=["Experiments"])
api_router.include_router(exports.router, prefix="/export", tags=["Exports"])
api_router.include_router(ept.router, prefix="/ept", tags=["EPT"])
api_router.include_router(forge.router, prefix="/forge", tags=["ForgeAgent"])
api_router.include_router(history.router, prefix="/history", tags=["History"])
api_router.include_router(schedule.router, prefix="/schedule", tags=["Schedule"])
api_router.include_router(websocket.router, tags=["WebSocket"])
