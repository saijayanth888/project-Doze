"""Resolve HuggingFace ``repo_id`` strings for training and evaluation.

Dashboards and Ollama use tags like ``llama3.2:3b``; ``transformers`` and the Hub
require ids such as ``meta-llama/Llama-3.2-3B-Instruct``.
"""

from __future__ import annotations

_DEFAULT_FALLBACK = "meta-llama/Llama-3.1-8B-Instruct"

# Lowercase Ollama-style tags -> canonical HF instruct checkpoints (common defaults).
_OLLAMA_TAG_TO_HF: dict[str, str] = {
    # Llama 3.x family
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
    # TinyLlama (the bare ollama tag has no `:size` so include both)
    "tinyllama": "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
    "tinyllama:1.1b": "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
    "tinyllama-1.1b": "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
    # Qwen 2.5
    "qwen2.5:1.5b": "Qwen/Qwen2.5-1.5B-Instruct",
    "qwen2.5-1.5b": "Qwen/Qwen2.5-1.5B-Instruct",
    "qwen2.5:3b": "Qwen/Qwen2.5-3B-Instruct",
    "qwen2.5-3b": "Qwen/Qwen2.5-3B-Instruct",
    "qwen2.5:7b": "Qwen/Qwen2.5-7B-Instruct",
    "qwen2.5-7b": "Qwen/Qwen2.5-7B-Instruct",
    "qwen2.5:72b": "Qwen/Qwen2.5-72B-Instruct",
    "qwen2.5:72b-instruct": "Qwen/Qwen2.5-72B-Instruct",
    # Qwen 3 — MoE 30B-A3B is the trading-bot's locked base per project_modelforge_decisions
    "qwen3:30b": "Qwen/Qwen3-30B-A3B-Instruct-2507",
    "qwen3-30b": "Qwen/Qwen3-30B-A3B-Instruct-2507",
    "qwen3:30b-instruct": "Qwen/Qwen3-30B-A3B-Instruct-2507",
    # Phi 3.5
    "phi3.5": "microsoft/Phi-3.5-mini-instruct",
    "phi3.5:mini": "microsoft/Phi-3.5-mini-instruct",
    "phi3.5-mini": "microsoft/Phi-3.5-mini-instruct",
    # Mistral 7B
    "mistral:7b": "mistralai/Mistral-7B-Instruct-v0.3",
    "mistral-7b": "mistralai/Mistral-7B-Instruct-v0.3",
    "mistral": "mistralai/Mistral-7B-Instruct-v0.3",
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
