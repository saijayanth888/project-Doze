import logging
import time

import httpx

logger = logging.getLogger("modelforge.ollama")

_GENERATE_TIMEOUT = 30.0
_HEALTH_TIMEOUT = 5.0


class OllamaClient:
    def __init__(self, host: str):
        # Strip trailing slash for consistent URL construction
        self._host = host.rstrip("/")

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> str:
        try:
            async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT) as client:
                resp = await client.get(f"{self._host}/api/tags")
                resp.raise_for_status()
                return "ok"
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.warning("Ollama health check failed: %s", exc)
            return "unreachable"
        except httpx.HTTPStatusError as exc:
            logger.warning("Ollama health check HTTP error: %s", exc)
            return "unreachable"

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------

    async def list_models(self) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT) as client:
                resp = await client.get(f"{self._host}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return data.get("models", [])
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise RuntimeError("Ollama unreachable") from exc

    # ------------------------------------------------------------------
    # Generate
    # ------------------------------------------------------------------

    async def generate(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 256,
        temperature: float = 0.7,
    ) -> dict:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=_GENERATE_TIMEOUT) as client:
                resp = await client.post(f"{self._host}/api/generate", json=payload)
                resp.raise_for_status()
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise RuntimeError("Ollama unreachable") from exc

        latency_ms = (time.perf_counter() - t0) * 1000
        data = resp.json()

        return {
            "response": data.get("response", ""),
            "model": data.get("model", model),
            "tokens": data.get("eval_count", 0),
            "latency_ms": round(latency_ms, 2),
        }

    # ------------------------------------------------------------------
    # Pull
    # ------------------------------------------------------------------

    async def pull_model(self, model: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(
                    f"{self._host}/api/pull",
                    json={"name": model},
                )
                resp.raise_for_status()
                return True
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise RuntimeError("Ollama unreachable") from exc
        except httpx.HTTPStatusError as exc:
            logger.error("pull_model %s failed: %s", model, exc)
            return False
