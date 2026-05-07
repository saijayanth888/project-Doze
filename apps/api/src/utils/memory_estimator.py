"""Coarse peak-VRAM estimator for LoRA training.

Numbers come from BF16 training measurements on the DGX-128GB box. We're
not trying to be exact — the goal is to refuse a job that would obviously
OOM (e.g. 70B with rank 64 batch 8) before it eats hours of queue time.
"""

from __future__ import annotations

# Base model footprint at bf16 (parameters * 2 bytes / 1024^3, rounded).
MODEL_SIZES_GB: dict[str, float] = {
    "TinyLlama/TinyLlama-1.1B-Chat-v1.0": 2.2,
    "meta-llama/Llama-3.2-1B-Instruct": 2.0,
    "meta-llama/Llama-3.2-3B-Instruct": 6.4,
    "Qwen/Qwen2.5-1.5B-Instruct": 3.0,
    "Qwen/Qwen2.5-3B-Instruct": 6.0,
    "Qwen/Qwen2.5-7B-Instruct": 14.0,
    "microsoft/Phi-3.5-mini-instruct": 7.6,
    "google/gemma-2-2b-it": 5.2,
    "google/gemma-2-9b-it": 18.4,
    "mistralai/Mistral-7B-Instruct-v0.3": 14.0,
    "meta-llama/Llama-3.1-8B-Instruct": 16.0,
}

_DEFAULT_BASE_GB = 14.0  # Assume 7B-class model for unknown ids.
_HEADROOM_GB = 18.0      # System / cudnn workspace / fragmentation buffer.


def estimate_training_memory(
    model_name: str,
    lora_rank: int = 16,
    batch_size: int = 2,
) -> dict:
    base = MODEL_SIZES_GB.get(model_name, _DEFAULT_BASE_GB)
    lora_overhead = base * 0.02 * (lora_rank / 16.0)
    optimizer_states = lora_overhead * 4.0  # Adam: m + v + state copy.
    activations = base * 0.3 * batch_size
    peak = base + lora_overhead + optimizer_states + activations
    return {
        "model_gb": round(base, 2),
        "lora_overhead_gb": round(lora_overhead, 2),
        "optimizer_gb": round(optimizer_states, 2),
        "activations_gb": round(activations, 2),
        "estimated_peak_gb": round(peak, 2),
        "fits_128gb": peak < (128.0 - _HEADROOM_GB),
    }
