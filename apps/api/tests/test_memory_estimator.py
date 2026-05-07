import pytest

from utils.memory_estimator import (
    MODEL_SIZES_GB,
    estimate_training_memory,
)


def test_known_model_3b_fits_128gb():
    est = estimate_training_memory("meta-llama/Llama-3.2-3B-Instruct", lora_rank=16, batch_size=2)
    assert est["model_gb"] == pytest.approx(MODEL_SIZES_GB["meta-llama/Llama-3.2-3B-Instruct"])
    assert est["fits_128gb"] is True


def test_unknown_model_uses_7b_default():
    est = estimate_training_memory("openai/totally-fake-model", lora_rank=16, batch_size=2)
    assert est["model_gb"] == 14.0


def test_lora_overhead_scales_with_rank():
    low = estimate_training_memory("meta-llama/Llama-3.2-3B-Instruct", lora_rank=8)
    high = estimate_training_memory("meta-llama/Llama-3.2-3B-Instruct", lora_rank=64)
    assert high["lora_overhead_gb"] > low["lora_overhead_gb"]


def test_70b_does_not_fit_128():
    MODEL_SIZES_GB.setdefault("__test/Big-70B", 140.0)
    est = estimate_training_memory("__test/Big-70B", lora_rank=16, batch_size=2)
    assert est["fits_128gb"] is False
