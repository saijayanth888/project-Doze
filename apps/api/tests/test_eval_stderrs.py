"""EvalResult.stderrs — per-task stderr captured from lm-eval-harness."""
from agents.eval_backend import EvalResult


def test_eval_result_has_stderrs_field_default_empty():
    r = EvalResult()
    assert hasattr(r, "stderrs")
    assert r.stderrs == {}


def test_eval_result_accepts_stderrs():
    r = EvalResult(scores={"mmlu": 0.5}, stderrs={"mmlu": 0.012})
    assert r.stderrs["mmlu"] == 0.012
