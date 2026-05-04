import json
import logging
from pathlib import Path

logger = logging.getLogger("modelforge.model_registry")

_REGISTRY_PATH = Path(__file__).parent.parent.parent / "data" / "registry.json"
_EMPTY_REGISTRY: dict = {"champion": None, "models": []}

try:
    from filelock import FileLock as _FileLock

    _filelock_available = True
except ImportError:
    _filelock_available = False
    logger.debug("filelock not installed; registry writes will use plain open()")


class ModelRegistry:
    def __init__(self, registry_path: Path | None = None):
        self._path = Path(registry_path) if registry_path else _REGISTRY_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._save(_EMPTY_REGISTRY)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        try:
            text = self._path.read_text(encoding="utf-8")
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError("Registry root must be a JSON object")
            data.setdefault("champion", None)
            data.setdefault("models", [])
            return data
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Registry file corrupted, resetting: %s", exc)
            empty = dict(_EMPTY_REGISTRY)
            self._save(empty)
            return empty

    def _save(self, data: dict) -> None:
        content = json.dumps(data, indent=2, default=str)
        if _filelock_available:
            lock_path = str(self._path) + ".lock"
            with _FileLock(lock_path):
                self._path.write_text(content, encoding="utf-8")
        else:
            self._path.write_text(content, encoding="utf-8")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_champion(self) -> dict | None:
        return self._load().get("champion")

    def set_champion(self, info: dict) -> None:
        data = self._load()
        data["champion"] = info
        self._save(data)

    def get_all_models(self) -> list[dict]:
        return self._load().get("models", [])

    def register_model(self, info: dict) -> None:
        data = self._load()
        data["models"].append(info)
        self._save(data)

    def get_model(self, model_id: str) -> dict | None:
        for model in self._load().get("models", []):
            if model.get("model_id") == model_id or model.get("id") == model_id:
                return model
        return None
