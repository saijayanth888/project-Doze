"""Per-model-family LoRA target modules.

The lm-eval-harness rebuild surfaced two facts:
  • Gemma-2 *requires* all 7 modules (Google's official PEFT recipe);
    the legacy 4-module attention-only set silently NO-OPs on Gemma.
  • Llama / Qwen / Phi / Mistral all benefit from including the MLP block
    (gate/up/down) — typical +1-2 pts on GSM8K.

Adding a model family here changes default training behaviour. Callers
that want to override pass ``target_modules`` explicitly in the run config.
"""

from __future__ import annotations

_ALL_LINEAR = (
    "q_proj",
    "k_proj",
    "v_proj",
    "o_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
)

_FAMILY_MODULES: dict[str, tuple[str, ...]] = {
    "tinyllama": _ALL_LINEAR,  # Llama arch
    "llama": _ALL_LINEAR,
    "qwen": _ALL_LINEAR,
    "phi": _ALL_LINEAR,
    "gemma": _ALL_LINEAR,  # MUST be all 7 per Google docs
    "mistral": _ALL_LINEAR,
}


def get_lora_target_modules(model_name: str) -> list[str]:
    """Return the LoRA target_modules list for ``model_name``.

    Falls back to ``_ALL_LINEAR`` for unknown families — that's the safest
    superset for any HF Llama-style architecture.
    """
    name = (model_name or "").lower()
    for family, mods in _FAMILY_MODULES.items():
        if family in name:
            return list(mods)
    return list(_ALL_LINEAR)
