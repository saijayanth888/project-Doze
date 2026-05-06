"""
DataCurator — Sources and generates training data targeting model weaknesses.

This is the "Self-Targeted Data Curation" component — the core IP of ModelForge.
The model identifies what it's bad at, then generates/selects training data
specifically to improve those weaknesses.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol

from config.settings import settings

logger = logging.getLogger("modelforge.curator")


@dataclass
class CurationResult:
    data_path: str
    num_samples: int
    categories_targeted: list[str]
    sources: list[str]


class DataCuratorBackend(Protocol):
    async def curate(
        self,
        *,
        weak_categories: list[str],
        weakness_report: str,
        generation: int,
        max_samples: int,
        config: dict,
    ) -> CurationResult: ...


# (dataset_name, dataset_config, split, suggested_n)
# `cais/mmlu` has no `train` split — the bulk pretraining-style data lives in `auxiliary_train`.
# `bigcode/humanevalpack` ships only a `test` split (HumanEval is a benchmark, not training data;
# we use it as instruction-tuning seed for code).
WEAKNESS_DATASETS: dict[str, list[tuple[str, str | None, str, int]]] = {
    "mmlu": [("cais/mmlu", "all", "auxiliary_train", 2000)],
    "arc_challenge": [("allenai/ai2_arc", "ARC-Challenge", "train", 1500)],
    "hellaswag": [("Rowan/hellaswag", None, "train", 1500)],
    "gsm8k": [("openai/gsm8k", "main", "train", 2000)],
    "humaneval": [("bigcode/humanevalpack", "python", "test", 1000)],
}


class MockDataCurator:
    name = "mock"

    async def curate(
        self,
        *,
        weak_categories: list[str],
        weakness_report: str,
        generation: int,
        max_samples: int,
        config: dict,
    ) -> CurationResult:
        await asyncio.sleep(0.3)
        n = min(max_samples, 1200 if weak_categories else 1000)
        path = str(settings.resolve_data_root() / "curated" / f"gen-{generation}")
        return CurationResult(
            data_path=path,
            num_samples=n,
            categories_targeted=list(weak_categories),
            sources=["mock"],
        )


class HuggingFaceDataCurator:
    name = "huggingface"

    def __init__(self) -> None:
        try:
            import datasets  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "HuggingFaceDataCurator requires `datasets` (pip install datasets)."
            ) from exc

    def _normalize_sample(self, category: str, example: dict[str, Any]) -> dict[str, Any] | None:
        # Best-effort normalization across the mapped datasets.
        if category == "gsm8k":
            q = example.get("question")
            a = example.get("answer")
            if q and a:
                return {"instruction": str(q), "response": str(a)}
        elif category == "mmlu":
            question = example.get("question")
            choices = example.get("choices") or example.get("options")
            answer = example.get("answer")
            if question and choices is not None and answer is not None:
                if isinstance(choices, list | tuple):
                    choice_lines = "\n".join([f"{i}. {c}" for i, c in enumerate(choices)])
                else:
                    choice_lines = str(choices)
                inst = f"{question}\n\nChoices:\n{choice_lines}\n\nAnswer with the correct choice."
                # Some configs store answer as index, others as string.
                resp = str(answer)
                return {"instruction": inst, "response": resp}
        elif category == "arc_challenge":
            q = (example.get("question") or {}).get("stem") if isinstance(example.get("question"), dict) else example.get("question")
            choices = example.get("choices") or (example.get("question") or {}).get("choices")
            answer_key = example.get("answerKey") or example.get("answer")
            if q and choices and answer_key:
                labels = choices.get("label") if isinstance(choices, dict) else None
                texts = choices.get("text") if isinstance(choices, dict) else None
                if labels and texts:
                    choice_lines = "\n".join(
                        [f"{lab}. {t}" for lab, t in zip(labels, texts, strict=False)]
                    )
                else:
                    choice_lines = str(choices)
                inst = f"{q}\n\nChoices:\n{choice_lines}\n\nAnswer with the correct choice label."
                return {"instruction": inst, "response": str(answer_key)}
        elif category == "hellaswag":
            ctx = example.get("ctx") or example.get("context")
            endings = example.get("endings") or example.get("choices")
            label = example.get("label") or example.get("answer")
            if ctx and endings is not None and label is not None:
                if isinstance(endings, list | tuple):
                    choice_lines = "\n".join([f"{i}. {c}" for i, c in enumerate(endings)])
                else:
                    choice_lines = str(endings)
                inst = f"{ctx}\n\nChoose the best continuation:\n{choice_lines}"
                return {"instruction": inst, "response": str(label)}
        elif category == "humaneval":
            prompt = example.get("prompt")
            canonical_solution = example.get("canonical_solution") or example.get("solution")
            if prompt and canonical_solution:
                inst = f"Complete the following Python function:\n\n{prompt}"
                return {"instruction": inst, "response": str(canonical_solution)}

        # Fallback: if it already looks like instruction/response.
        if "instruction" in example and "response" in example:
            return {"instruction": str(example["instruction"]), "response": str(example["response"])}
        if "question" in example and "response" in example:
            return {"instruction": str(example["question"]), "response": str(example["response"])}
        return None

    async def curate(
        self,
        *,
        weak_categories: list[str],
        weakness_report: str,
        generation: int,
        max_samples: int,
        config: dict,
    ) -> CurationResult:
        from datasets import Dataset, load_dataset  # lazy-ish (constructor already gated)

        categories = [c for c in weak_categories if c in WEAKNESS_DATASETS]
        if not categories:
            categories = list(WEAKNESS_DATASETS.keys())

        samples: list[dict[str, Any]] = []
        sources: list[str] = []

        logger.info(
            "[curator] gen=%d targeting=%s max_samples=%d report=%s",
            generation,
            categories,
            max_samples,
            weakness_report[:200],
        )

        # Lazy import — keeps the curator usable in environments without the
        # api package on the path (e.g. one-off scripts).
        try:
            from services import run_events as _run_events
        except Exception:
            _run_events = None
        run_id = str((config or {}).get("run_id") or "") if isinstance(config, dict) else ""

        per_cat_budget = max(1, int(max_samples / max(1, len(categories))))
        for category in categories:
            for ds_name, ds_config, split_name, suggested_n in WEAKNESS_DATASETS.get(category, []):
                take_n = min(per_cat_budget, suggested_n)
                split_spec = f"{split_name}[:{take_n}]"
                try:
                    ds = load_dataset(ds_name, ds_config, split=split_spec)
                except Exception as exc:
                    logger.warning(
                        "[curator] failed to load %s/%s split=%s: %s",
                        ds_name, ds_config, split_spec, exc,
                    )
                    if _run_events and run_id:
                        _run_events.publish(
                            run_id, phase="curate", level="warn",
                            label=f"failed to load {ds_name} ({split_spec})",
                            sub=str(exc)[:200], generation=generation,
                        )
                    continue

                added_for_source = 0
                for ex in ds:
                    norm = self._normalize_sample(category, ex)
                    if norm is None:
                        continue
                    samples.append(
                        {
                            "category": category,
                            "source": "huggingface",
                            "dataset_name": ds_name,
                            "instruction": norm["instruction"],
                            "response": norm["response"],
                        }
                    )
                    added_for_source += 1
                    if len(samples) >= max_samples:
                        break
                sources.append(ds_name)
                if _run_events and run_id:
                    _run_events.publish(
                        run_id, phase="curate",
                        label=f"+{added_for_source} from {ds_name}",
                        sub=f"{category} · split {split_name} · total now {len(samples)}/{max_samples}",
                        metric={"category": category, "added": added_for_source, "total": len(samples)},
                        generation=generation,
                    )
                if len(samples) >= max_samples:
                    break
            if len(samples) >= max_samples:
                break

        out_dir = str(settings.resolve_data_root() / "curated" / f"gen-{generation}")
        os.makedirs(out_dir, exist_ok=True)

        ds_out = Dataset.from_list(samples)
        ds_out.save_to_disk(out_dir)

        # `Dataset.save_to_disk()` writes its own dataset_info.json without
        # `num_samples`, `categories`, or `sources`. Persist a small sidecar
        # `mf_meta.json` so the API listing can show real metadata without
        # re-loading the arrow shard.
        try:
            import json as _json
            meta_path = os.path.join(out_dir, "mf_meta.json")
            with open(meta_path, "w", encoding="utf-8") as fh:
                _json.dump(
                    {
                        "num_samples": int(len(ds_out)),
                        "categories": list(categories),
                        "sources": sorted(set(sources)) if sources else ["huggingface"],
                        "weakness_report": str(weakness_report)[:500],
                        "max_samples": int(max_samples),
                        "generation": int(generation),
                    },
                    fh,
                )
        except Exception as exc:
            logger.debug("[curator] mf_meta.json write skipped: %s", exc)

        logger.info("[curator] saved %d samples to %s", len(ds_out), out_dir)

        return CurationResult(
            data_path=out_dir,
            num_samples=len(ds_out),
            categories_targeted=categories,
            sources=sorted(set(sources)) if sources else ["huggingface"],
        )

