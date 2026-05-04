"""Runtime settings loaded from environment + .env via pydantic-settings v2.

The settings object is the single source of truth for every external
hostname, secret, and tunable. It performs two important production
guards:

1. When ``environment == "production"`` the API key MUST be set, otherwise
   the application refuses to start.
2. When ``cors_origins`` contains a ``*`` wildcard, ``allow_credentials``
   is forced to ``False`` (CORS spec — browsers reject the combination).
"""

from __future__ import annotations

import logging

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("modelforge.settings")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── App ────────────────────────────────────────────
    environment: str = "development"
    log_level: str = "INFO"

    # ── Auth ───────────────────────────────────────────
    # X-API-Key checked by APIKeyMiddleware. Required in production.
    api_key: str | None = Field(default=None, alias="MODELFORGE_API_KEY")

    # ── CORS ───────────────────────────────────────────
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # ── Database ───────────────────────────────────────
    database_url: str = "postgresql+asyncpg://modelforge:modelforge@localhost:5432/modelforge"
    db_pool_min: int = 2
    db_pool_max: int = 10

    # ── Redis ──────────────────────────────────────────
    redis_url: str = "redis://localhost:6379"

    # ── Inference backends ─────────────────────────────
    ollama_host: str = "http://localhost:11434"
    vllm_host: str = "http://localhost:8001"
    vllm_api_key: str | None = None

    # ── n8n ────────────────────────────────────────────
    n8n_host: str = "http://localhost:5679"
    n8n_basic_auth_user: str = "admin"
    n8n_basic_auth_password: str | None = None
    # Evolution agent POSTs JSON to this URL (production: n8n webhook).
    n8n_webhook_evolution_url: str | None = Field(
        default=None,
        alias="N8N_WEBHOOK_EVOLUTION_URL",
    )
    # Optional HMAC for evolution webhook (shared with n8n Code node / $env.N8N_WEBHOOK_SECRET).
    n8n_webhook_secret: str | None = Field(default=None, alias="N8N_WEBHOOK_SECRET")

    # ── External APIs (optional) ───────────────────────
    hf_token: str | None = None
    wandb_api_key: str | None = None
    anthropic_api_key: str | None = None

    # ── Evolution defaults ─────────────────────────────
    default_base_model: str = "llama3.2:3b"
    default_max_generations: int = 10
    default_lora_rank: int = 16
    default_lora_alpha: int = 32
    default_learning_rate: float = 2e-4
    default_batch_size: int = 2

    # ── Validators ─────────────────────────────────────
    @field_validator("environment")
    @classmethod
    def _normalize_env(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, v: str) -> str:
        return v.strip().upper()

    # ── Computed helpers ───────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def cors_has_wildcard(self) -> bool:
        return "*" in self.cors_origin_list

    def validate_for_runtime(self) -> None:
        """Raise if the configuration is unsafe for the chosen environment.

        Called once from the FastAPI lifespan startup.
        """
        if self.is_production and not self.api_key:
            raise RuntimeError("MODELFORGE_API_KEY must be set when ENVIRONMENT=production")
        if self.is_production and self.cors_has_wildcard:
            logger.warning(
                "CORS_ORIGINS contains '*' in production — "
                "credentials will be disabled to comply with the CORS spec."
            )


settings = Settings()
