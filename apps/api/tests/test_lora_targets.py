import pytest

from utils.lora_targets import get_lora_target_modules


@pytest.mark.parametrize(
    "model_name,expected_subset",
    [
        ("meta-llama/Llama-3.2-3B-Instruct", {"q_proj", "gate_proj"}),
        ("Qwen/Qwen2.5-3B-Instruct", {"k_proj", "down_proj"}),
        ("microsoft/Phi-3.5-mini-instruct", {"v_proj", "up_proj"}),
        ("google/gemma-2-2b-it", {"o_proj", "gate_proj"}),
        ("mistralai/Mistral-7B-Instruct-v0.3", {"q_proj", "down_proj"}),
        ("TinyLlama/TinyLlama-1.1B-Chat-v1.0", {"k_proj", "up_proj"}),
        # Unknown family falls back to the safe all-linear list.
        ("openai/totally-fake-model", {"q_proj", "gate_proj"}),
    ],
)
def test_get_lora_target_modules_includes_mlp(model_name, expected_subset):
    mods = set(get_lora_target_modules(model_name))
    assert expected_subset.issubset(mods), f"missing modules for {model_name}: {expected_subset - mods}"
    assert "gate_proj" in mods or "down_proj" in mods


def test_case_insensitive_match():
    assert get_lora_target_modules("META-LLAMA/Llama-3.2-3B") == get_lora_target_modules(
        "meta-llama/llama-3.2-3b"
    )


def test_returns_a_fresh_list_each_call():
    a = get_lora_target_modules("meta-llama/Llama-3.2-3B-Instruct")
    a.append("MUTATED")
    b = get_lora_target_modules("meta-llama/Llama-3.2-3B-Instruct")
    assert "MUTATED" not in b


def test_training_backend_imports_helper():
    """If the import line gets refactored away by mistake, this test catches it."""
    import importlib

    mod = importlib.import_module("agents.training_backend")
    assert hasattr(mod, "get_lora_target_modules")
