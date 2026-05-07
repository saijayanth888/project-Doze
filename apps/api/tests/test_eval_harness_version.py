"""EvalResult must surface lm_eval.__version__ so experiment records can
attribute scores to a specific harness build (paper reproducibility)."""
from __future__ import annotations

from agents.eval_backend import EvalResult


def test_eval_result_has_harness_version_field():
    r = EvalResult()
    assert hasattr(r, "harness_version")
    assert r.harness_version == ""


def test_eval_result_accepts_harness_version_kwarg():
    r = EvalResult(scores={"mmlu": 0.5}, duration_seconds=1.0, harness_version="0.4.4")
    assert r.harness_version == "0.4.4"
