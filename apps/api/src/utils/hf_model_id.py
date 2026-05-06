"""Resolve HuggingFace ``repo_id`` strings for training and evaluation.

Dashboards and Ollama use tags like ``llama3.2:3b``; ``transformers`` and the Hub
require ids such as ``meta-llama/Llama-3.2-3B-Instruct``.
"""

from __future__ import annotations

_DEFAULT_FALLBACK = "meta-llama/Llama-3.1-8B-Instruct"

# Lowercase Ollama-style tags -> canonical HF instruct checkpoints (common defaults).
_OLLAMA_TAG_TO_HF: dict[str, str] = {
    "llama3.2:3b": "meta-llama/Llama-3.2-3B-Instruct",
    "llama3.2-3b": "meta-llama/Llama-3.2-3B-Instruct",
    "llama3.2:1b": "meta-llama/Llama-3.2-1B-Instruct",
    "llama3.2-1b": "meta-llama/Llama-3.2-1B-Instruct",
    "llama3.1:8b": "meta-llama/Llama-3.1-8B-Instruct",
    "llama3.1-8b": "meta-llama/Llama-3.1-8B-Instruct",
    "llama3.1:70b": "meta-llama/Llama-3.1-70B-Instruct",
    "llama3.1-70b": "meta-llama/Llama-3.1-70B-Instruct",
    "llama3:8b": "meta-llama/Meta-Llama-3-8B-Instruct",
    "llama3-8b": "meta-llama/Meta-Llama-3-8B-Instruct",
}


def resolve_hf_base_model_id(
    raw: str | None,
    *,
    env_fallback: str | None = None,
) -> str:
    """Return a string suitable for ``AutoModel.from_pretrained`` / lm-eval ``pretrained=``."""
    s = (raw or "").strip()
    fb = (env_fallback or _DEFAULT_FALLBACK).strip() or _DEFAULT_FALLBACK

    if not s:
        return fb

    # Typical Hub id: org/name (dots allowed; revision uses @ or : in some tools — we keep simple heuristics).
    if "/" in s:
        first, rest = s.split("/", 1)
        if first and rest and not first.startswith(":"):
            return s

    key = s.lower()
    if key in _OLLAMA_TAG_TO_HF:
        return _OLLAMA_TAG_TO_HF[key]

    # Bare tag with colon (Ollama) but unmapped — avoid passing invalid "repo id" to the Hub.
    if ":" in s:
        return fb

    return s
