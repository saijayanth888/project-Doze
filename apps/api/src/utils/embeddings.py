import hashlib
import logging

logger = logging.getLogger("modelforge.embeddings")

_EMBEDDING_DIM = 384
_model_singleton: object | None = None
_sentence_transformers_available: bool | None = None


def _get_model():
    global _model_singleton, _sentence_transformers_available

    if _sentence_transformers_available is False:
        return None

    if _model_singleton is not None:
        return _model_singleton

    try:
        from sentence_transformers import SentenceTransformer

        _model_singleton = SentenceTransformer("all-MiniLM-L6-v2")
        _sentence_transformers_available = True
        logger.info("Loaded SentenceTransformer all-MiniLM-L6-v2")
        return _model_singleton
    except Exception as exc:
        logger.warning("sentence_transformers unavailable, using deterministic fallback: %s", exc)
        _sentence_transformers_available = False
        return None


def _deterministic_embedding(text: str) -> list[float]:
    """
    Produce a deterministic 384-dim float vector in [-1, 1] from the MD5 of text.
    Repeats the 16-byte digest as many times as needed to fill 384 dimensions.
    """
    digest = hashlib.md5(text.encode("utf-8")).digest()
    result: list[float] = []
    while len(result) < _EMBEDDING_DIM:
        for byte in digest:
            result.append((byte / 127.5) - 1.0)
            if len(result) == _EMBEDDING_DIM:
                break
    return result


def text_to_embedding(text: str) -> list[float]:
    model = _get_model()
    if model is not None:
        try:
            vector = model.encode(text, convert_to_numpy=True)
            return vector.tolist()
        except Exception as exc:
            logger.warning("Embedding model encode failed, using fallback: %s", exc)

    return _deterministic_embedding(text)
