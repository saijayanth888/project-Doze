"""GPU-side base + PEFT-adapter inference for the Playground.

Ollama only ingests GGUF LoRA adapters; our training pipeline writes PEFT
(safetensors) adapters. To give the user an honest "base vs adapter" comparison
we load the base model and apply the PEFT weights here in-process.

Models stay warm in a tiny LRU so consecutive Playground hits don't re-pay the
2-3GB safetensors load. The cache key is the resolved HF base id; switching to
a different base evicts the previous one.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path

from config.settings import settings
from utils.hf_model_id import resolve_hf_base_model_id

logger = logging.getLogger("modelforge.peft_inference")

# Tiny LRU: { base_id: (model, tokenizer) }. The PEFT layer is attached/detached
# per call so a single base in memory can serve many adapters cheaply.
_BASE_CACHE: "OrderedDict[str, tuple]" = OrderedDict()
_CACHE_LIMIT = 1
_LOCK = threading.Lock()


def _get_base(base_id: str):
    """Load and cache the base model + tokenizer. Synchronous + thread-safe."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    with _LOCK:
        if base_id in _BASE_CACHE:
            _BASE_CACHE.move_to_end(base_id)
            return _BASE_CACHE[base_id]

        logger.info("[peft-infer] loading base model %s", base_id)
        t0 = time.perf_counter()
        tok = AutoTokenizer.from_pretrained(base_id, use_fast=True)
        if tok.pad_token is None:
            tok.pad_token = tok.eos_token

        dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float16
        model = AutoModelForCausalLM.from_pretrained(
            base_id,
            torch_dtype=dtype,
            device_map="auto" if torch.cuda.is_available() else None,
        )
        model.eval()
        logger.info("[peft-infer] loaded base %s in %.1fs", base_id, time.perf_counter() - t0)

        _BASE_CACHE[base_id] = (model, tok)
        while len(_BASE_CACHE) > _CACHE_LIMIT:
            evicted_id, _ = _BASE_CACHE.popitem(last=False)
            logger.info("[peft-infer] evicted %s from base cache", evicted_id)
        return _BASE_CACHE[base_id]


def _format_prompt_for_chat(tokenizer, prompt: str) -> str:
    """Apply the model's chat template if it has one; otherwise pass through."""
    try:
        return tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=False,
            add_generation_prompt=True,
        )
    except Exception:
        return prompt


def _generate(
    *,
    model,
    tokenizer,
    prompt: str,
    max_tokens: int,
    temperature: float,
) -> tuple[str, int]:
    import torch

    text = _format_prompt_for_chat(tokenizer, prompt)
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=4096)
    if torch.cuda.is_available():
        inputs = {k: v.to("cuda") for k, v in inputs.items()}
    with torch.no_grad():
        gen = model.generate(
            **inputs,
            max_new_tokens=int(max_tokens),
            do_sample=temperature > 0,
            temperature=max(0.01, float(temperature)),
            top_p=0.95,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    new_tokens = gen[0][inputs["input_ids"].shape[1]:]
    out = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
    return out, int(new_tokens.shape[0])


def adapter_dir_from_id(adapter_id: str) -> Path:
    """`run-abc__gen1` → `<data>/adapters/run-abc/gen-1`."""
    if "__gen" not in adapter_id:
        raise ValueError(f"adapter_id must look like run-XXX__genN, got {adapter_id!r}")
    run_id, gen_part = adapter_id.split("__gen", 1)
    try:
        gen = int(gen_part)
    except ValueError as exc:
        raise ValueError(f"bad generation in adapter_id {adapter_id!r}") from exc
    return settings.resolve_data_root() / "adapters" / run_id / f"gen-{gen}"


def run_with_adapter_sync(
    *,
    base_model_raw: str | None,
    adapter_id: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
) -> dict:
    """Apply the PEFT adapter and generate. Returns {response, tokens,
    latency_ms, model, base_model, adapter_id}.

    Synchronous — call via `loop.run_in_executor` from FastAPI. The PEFT layer
    is unloaded at the end so the base remains shareable for subsequent calls
    (against the same base or with a different adapter)."""
    import torch
    from peft import PeftModel

    adapter_path = adapter_dir_from_id(adapter_id)
    if not adapter_path.is_dir():
        raise FileNotFoundError(f"adapter dir missing: {adapter_path}")
    # Many failed/aborted runs leave an empty adapter dir behind. Catch this
    # explicitly so callers see "no weights" instead of a confusing
    # huggingface_hub error about repo ids.
    if not (adapter_path / "adapter_config.json").is_file():
        raise FileNotFoundError(
            f"adapter has no weights at {adapter_path} "
            "(adapter_config.json missing — training likely failed before "
            "checkpoint save)"
        )

    base_id = resolve_hf_base_model_id(base_model_raw or None)
    base_model, tok = _get_base(base_id)

    t0 = time.perf_counter()
    peft_model = PeftModel.from_pretrained(base_model, str(adapter_path))
    try:
        out, n_tokens = _generate(
            model=peft_model,
            tokenizer=tok,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    finally:
        # Detach the adapter so the base stays clean for the next request.
        try:
            peft_model.unload()
        except Exception:
            pass
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    latency_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "response": out,
        "tokens": n_tokens,
        "latency_ms": latency_ms,
        "model": f"{base_id} + {adapter_id}",
        "base_model": base_id,
        "adapter_id": adapter_id,
    }


def run_base_sync(
    *,
    base_model_raw: str | None,
    prompt: str,
    max_tokens: int,
    temperature: float,
) -> dict:
    """Same as above but without the adapter — paired with run_with_adapter_sync
    to power /api/infer/adapter/compare."""
    base_id = resolve_hf_base_model_id(base_model_raw or None)
    base_model, tok = _get_base(base_id)
    t0 = time.perf_counter()
    out, n_tokens = _generate(
        model=base_model,
        tokenizer=tok,
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    latency_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "response": out,
        "tokens": n_tokens,
        "latency_ms": latency_ms,
        "model": base_id,
        "base_model": base_id,
        "adapter_id": None,
    }


def is_available() -> bool:
    """True iff the API process can host PEFT inference (cuda + libs available)."""
    try:
        import torch  # noqa: F401
        import peft  # noqa: F401
        return True
    except Exception:
        return False


# Suppress an annoying CUDA warning that prints on every adapter unload.
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
