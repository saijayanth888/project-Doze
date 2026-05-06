"""ForgeAgent — classifier-routed inference across specialist tracks.

Pipeline
--------
::

    user prompt → classify_prompt() → ForgeRoute → execute_route() → ForgeAnswer

* :func:`classify_prompt` picks the most likely track using keyword scoring
  first, falling back to an Ollama-served small LLM only when keywords are
  ambiguous. Returns a confidence + reason for transparency.
* :func:`execute_route` runs inference with that track's champion PEFT
  adapter when available, otherwise falls back to the base model via
  Ollama (which is faster on the GB10 host for raw inference).

Tracks are owned by :mod:`services.track_seed` / ``evolution_tracks`` table.
This module reads them at request time so a freshly-promoted champion
takes effect immediately.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from config.settings import settings

logger = logging.getLogger("modelforge.agents.forge")


# ── Keyword scoring ───────────────────────────────────────────────────

# Per-track patterns. Weighted: each hit adds the listed weight to that
# track's score. Pre-compiled because every prompt runs through all of them.

@dataclass
class _TrackPatterns:
    track_id: str
    patterns: list[tuple[re.Pattern, float]]


# Keywords are intentionally short and high-signal. Misses fall through to
# the LLM classifier; false positives are visible in the routing reason.
_DEFAULT_PATTERNS: dict[str, list[tuple[str, float]]] = {
    "math": [
        (r"\bcalculate\b|\bcompute\b|\bsolve\b|\bevaluate\b", 2.0),
        (r"\b(sum|product|difference|quotient|average|mean|median|mode)\b", 2.0),
        (r"\b(equation|inequality|integral|derivative|matrix|vector)\b", 2.5),
        (r"\b\d+\s*[\+\-\*\/×÷]\s*\d+\b", 3.0),                # 2+3, 5*7
        (r"\bwhat is \d", 2.0),                                # "what is 2+3"
        (r"\b(percent|percentage|fraction|decimal|prime)\b", 1.5),
        (r"\b(algebra|geometry|trigonometry|calculus|statistics|probability)\b", 2.0),
        (r"\bx\s*=\b|\by\s*=\b", 1.5),
        (r"\bword\s*problem\b", 2.5),
    ],
    "code": [
        (r"```|`[^`]+`", 3.0),                                  # backticks
        (r"\bdef\s+\w+\s*\(|\bfunction\s+\w+\s*\(|\bclass\s+\w+\b", 3.0),
        (r"\b(python|javascript|typescript|rust|golang|java|c\+\+|sql)\b", 2.5),
        (r"\b(bug|error|exception|stack\s*trace|traceback|stacktrace)\b", 2.0),
        (r"\b(write|implement|refactor|debug|fix)\s+(a\s+)?(function|method|class|code)\b", 2.5),
        (r"\b(api|endpoint|http|json|yaml|regex|cli|library|package|framework)\b", 1.0),
        (r"\b(algorithm|data\s*structure|recursion|complexity|big\s*o)\b", 2.0),
        (r"\bpip\s+install\b|\bnpm\s+install\b|\bcargo\s+\w+\b", 2.0),
    ],
    "reasoning": [
        (r"\bwhy\b|\bbecause\b|\bexplain why\b", 1.5),
        (r"\b(compare|contrast|difference\s+between|similarit(?:y|ies))\b", 2.0),
        (r"\b(reason|reasoning|logic|argument|implication|inference|deduce)\b", 2.0),
        (r"\b(should\s+i|should\s+we|how\s+would|what\s+if)\b", 1.5),
        (r"\b(pros\s+and\s+cons|trade-?off|trade-?offs)\b", 2.0),
        (r"\b(analyze|evaluate|assess|critique)\b", 1.5),
        (r"\b(read|story|paragraph|passage|excerpt)\b.*\?", 1.5),
    ],
    "general": [
        (r"\bwhat\s+(is|are|was|were)\b", 1.0),
        (r"\bwho\s+(is|was|are|were)\b", 1.5),
        (r"\bwhen\s+(did|was|were|do|does)\b", 1.5),
        (r"\bwhere\s+(is|was|are|were)\b", 1.5),
        (r"\b(history|geography|biology|chemistry|physics|literature|art|music)\b", 1.5),
        (r"\b(definition|define|meaning of)\b", 1.0),
    ],
}


def _compile_patterns() -> dict[str, _TrackPatterns]:
    out: dict[str, _TrackPatterns] = {}
    for track_id, raw in _DEFAULT_PATTERNS.items():
        out[track_id] = _TrackPatterns(
            track_id=track_id,
            patterns=[(re.compile(p, re.IGNORECASE), w) for p, w in raw],
        )
    return out


_PATTERNS = _compile_patterns()


# ── Result envelopes ─────────────────────────────────────────────────


@dataclass
class TrackScore:
    track_id: str
    score: float
    matches: list[str] = field(default_factory=list)


@dataclass
class ForgeRoute:
    track_id: str           # e.g. "code"
    track_name: str         # e.g. "Code Specialist"
    method: str             # "keyword" | "llm" | "fallback"
    confidence: float       # 0..1
    reason: str             # human-readable explanation
    all_scores: list[dict]  # for the UI's "why this track?" panel
    track: dict[str, Any] = field(default_factory=dict)  # full track row


@dataclass
class ForgeAnswer:
    route: ForgeRoute
    response: str
    backend: str            # "peft" | "ollama"
    model: str              # "<base> + <adapter_id>" or "<base>"
    adapter_id: str | None
    tokens: int
    latency_ms: float
    base_model: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": {
                "track_id": self.route.track_id,
                "track_name": self.route.track_name,
                "method": self.route.method,
                "confidence": round(self.route.confidence, 3),
                "reason": self.route.reason,
                "all_scores": self.route.all_scores,
                "track": self.route.track,
            },
            "response": self.response,
            "backend": self.backend,
            "model": self.model,
            "adapter_id": self.adapter_id,
            "tokens": int(self.tokens),
            "latency_ms": round(self.latency_ms, 1),
            "base_model": self.base_model,
        }


# ── Track loading ────────────────────────────────────────────────────


async def _load_tracks(db) -> list[dict[str, Any]]:
    try:
        return await db.list_tracks()
    except Exception as exc:
        logger.warning("forge: list_tracks failed: %s", exc)
        return []


def _track_by_id(tracks: list[dict], track_id: str) -> dict | None:
    for t in tracks:
        if t.get("track_id") == track_id:
            return t
    return None


# ── Classifier ───────────────────────────────────────────────────────


def _score_keywords(prompt: str) -> list[TrackScore]:
    """Per-track keyword score for the prompt."""
    out: list[TrackScore] = []
    for track_id, tp in _PATTERNS.items():
        score = 0.0
        matches: list[str] = []
        for pat, w in tp.patterns:
            m = pat.search(prompt)
            if m:
                score += w
                matches.append(m.group(0)[:30])
        out.append(TrackScore(track_id=track_id, score=round(score, 2), matches=matches))
    return sorted(out, key=lambda s: s.score, reverse=True)


def _keyword_decision(scores: list[TrackScore]) -> tuple[str | None, float, str]:
    """Decide a winner from keyword scores. Returns (track_id_or_none, confidence, reason).

    Confidence rules:
      * Top score must be ≥ 2.0 to count at all.
      * If second is < 50% of first → confident keyword pick.
      * Else → ambiguous, request LLM tiebreak.
    """
    if not scores or scores[0].score < 2.0:
        return None, 0.0, "no strong keyword signal"
    top, second = scores[0], (scores[1] if len(scores) > 1 else None)
    if second and second.score >= top.score * 0.5:
        return None, 0.0, (
            f"ambiguous keywords: {top.track_id}={top.score} vs {second.track_id}={second.score}"
        )
    confidence = min(1.0, top.score / 6.0)
    matches_preview = ", ".join(f"'{m}'" for m in top.matches[:3])
    reason = f"keyword score {top.score} (matched: {matches_preview})"
    return top.track_id, confidence, reason


async def _llm_classify(
    prompt: str,
    *,
    track_options: list[dict],
    teacher_tag: str,
    ollama_host: str,
    timeout_s: float = 8.0,
) -> tuple[str | None, float, str]:
    """Ask a small Ollama-served LLM which track best fits the prompt.

    Returns (track_id_or_none, confidence, reason).
    """
    if not track_options:
        return None, 0.0, "no tracks configured"
    options_text = "\n".join(
        f"- {t['track_id']}: {t.get('name','')}. {t.get('description','')}"
        for t in track_options
    )
    classify_prompt = (
        "You are routing a user question to the best-suited specialist.\n"
        "Reply with ONLY the specialist id from the list — no other text.\n\n"
        f"Specialists:\n{options_text}\n\n"
        f"User question: {prompt[:500]}\n\n"
        "Specialist id:"
    )
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(
                f"{ollama_host.rstrip('/')}/api/generate",
                json={
                    "model": teacher_tag,
                    "prompt": classify_prompt,
                    "stream": False,
                    "options": {"temperature": 0.0, "num_predict": 16},
                },
            )
            if resp.status_code >= 400:
                return None, 0.0, f"llm classify HTTP {resp.status_code}"
            text = (resp.json().get("response") or "").strip().lower()
    except Exception as exc:
        return None, 0.0, f"llm classify failed: {exc}"

    # Find the first known track id mentioned in the response.
    valid_ids = [t["track_id"] for t in track_options]
    chosen: str | None = None
    for tid in valid_ids:
        if tid in text:
            chosen = tid
            break
    if not chosen:
        # Sometimes it returns a name — match against name lower.
        for t in track_options:
            if str(t.get("name", "")).lower() in text:
                chosen = t["track_id"]
                break
    if not chosen:
        return None, 0.0, f"llm answered {text[:40]!r}, no match"
    return chosen, 0.65, f"llm tiebreak: {teacher_tag} chose '{chosen}'"


async def classify_prompt(prompt: str, *, db, ollama_host: str | None = None) -> ForgeRoute:
    """Decide which track owns ``prompt``. Always returns a ``ForgeRoute`` —
    falls back to the ``general`` track (or the first available) when the
    classifier is uncertain."""
    tracks = await _load_tracks(db)
    enabled_tracks = [t for t in tracks if t.get("enabled")]
    enabled_ids = {t["track_id"] for t in enabled_tracks}

    # 1) Keyword scoring (cheap).
    scores = _score_keywords(prompt or "")
    enabled_scores = [s for s in scores if s.track_id in enabled_ids]
    chosen_id, conf, reason = _keyword_decision(enabled_scores)
    method = "keyword"

    # 2) LLM tiebreak only when keywords are ambiguous AND ollama is reachable.
    if not chosen_id and enabled_tracks:
        host = ollama_host or os.environ.get(
            "OLLAMA_HOST", "http://host.docker.internal:11434"
        )
        teacher = os.environ.get("MODELFORGE_FORGE_CLASSIFIER", "llama3.2:3b")
        chosen_id, conf, reason = await _llm_classify(
            prompt, track_options=enabled_tracks, teacher_tag=teacher, ollama_host=host,
        )
        if chosen_id:
            method = "llm"

    # 3) Final fallback — never throw, always pick something.
    if not chosen_id:
        if any(t["track_id"] == "general" for t in enabled_tracks):
            chosen_id = "general"
        elif enabled_tracks:
            chosen_id = enabled_tracks[0]["track_id"]
        method = "fallback"
        if not reason:
            reason = "no classifier signal — defaulting to general"
        else:
            reason = f"{reason}; falling back to {chosen_id}"
        conf = 0.2

    track = _track_by_id(tracks, chosen_id) or {}
    return ForgeRoute(
        track_id=chosen_id,
        track_name=str(track.get("name") or chosen_id),
        method=method,
        confidence=float(conf),
        reason=reason,
        all_scores=[
            {"track_id": s.track_id, "score": s.score, "matches": s.matches}
            for s in scores
        ],
        track=track,
    )


# ── Execution ────────────────────────────────────────────────────────


async def _ollama_generate(
    *,
    base_model: str, prompt: str, max_tokens: int, temperature: float,
    ollama_host: str,
) -> tuple[str, int, float]:
    """Call Ollama for raw base-model inference. Returns (text, tokens, latency_ms)."""
    t0 = time.perf_counter()
    body = {
        "model": base_model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": float(temperature), "num_predict": int(max_tokens)},
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{ollama_host.rstrip('/')}/api/generate", json=body)
        resp.raise_for_status()
        data = resp.json()
    text = str(data.get("response") or "").strip()
    eval_count = int(data.get("eval_count") or 0)
    latency_ms = (time.perf_counter() - t0) * 1000.0
    return text, eval_count, latency_ms


def _adapter_id_from_track(track: dict) -> str | None:
    """Translate a track row's champion fields into an adapter_id understood by
    ``services.peft_inference.adapter_dir_from_id``."""
    run_id = track.get("champion_run_id")
    gen = track.get("champion_generation")
    if not run_id or not gen:
        return None
    try:
        return f"{run_id}__gen{int(gen)}"
    except Exception:
        return None


async def execute_route(
    route: ForgeRoute,
    *,
    prompt: str,
    max_tokens: int = 256,
    temperature: float = 0.7,
    ollama_host: str | None = None,
    base_model_default: str | None = None,
    force_base: bool = False,
) -> ForgeAnswer:
    """Run inference for a routed prompt. Prefers PEFT (if track has a champion
    adapter), falls back to Ollama with the track's base model.

    ``force_base`` skips the PEFT path even when an adapter exists — useful for
    A/B comparisons in the UI.
    """
    track = route.track or {}
    base_model = (
        track.get("base_model")
        or base_model_default
        or os.environ.get("MODELFORGE_BASE_MODEL")
        or "llama3.2:3b"
    )
    adapter_id = None if force_base else _adapter_id_from_track(track)

    # PEFT path only when we have an adapter AND the inference module is loaded.
    if adapter_id:
        try:
            from services.peft_inference import is_available, run_with_adapter_sync
            if is_available():
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: run_with_adapter_sync(
                        base_model_raw=base_model,
                        adapter_id=adapter_id,
                        prompt=prompt,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    ),
                )
                return ForgeAnswer(
                    route=route,
                    response=result.get("response") or "",
                    backend="peft",
                    model=str(result.get("model") or f"{base_model} + {adapter_id}"),
                    adapter_id=adapter_id,
                    tokens=int(result.get("tokens") or 0),
                    latency_ms=float(result.get("latency_ms") or 0.0),
                    base_model=str(result.get("base_model") or base_model),
                )
        except FileNotFoundError as exc:
            logger.warning("forge: PEFT adapter missing for %s — falling back to ollama: %s",
                           route.track_id, exc)
        except Exception as exc:
            logger.warning("forge: PEFT path failed (%s) — falling back to ollama", exc)

    # Ollama fallback.
    host = ollama_host or os.environ.get(
        "OLLAMA_HOST", "http://host.docker.internal:11434"
    )
    text, n_tok, lat = await _ollama_generate(
        base_model=_to_ollama_tag(base_model),
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        ollama_host=host,
    )
    return ForgeAnswer(
        route=route,
        response=text,
        backend="ollama",
        model=_to_ollama_tag(base_model),
        adapter_id=None,
        tokens=n_tok,
        latency_ms=lat,
        base_model=_to_ollama_tag(base_model),
    )


_HF_TO_OLLAMA = {
    "meta-llama/llama-3.2-3b-instruct": "llama3.2:3b",
    "meta-llama/llama-3.2-1b-instruct": "llama3.2:1b",
    "meta-llama/llama-3-8b-instruct":   "llama3:8b",
    "tinyllama/tinyllama-1.1b-chat-v1.0": "tinyllama:1.1b",
    "qwen/qwen2.5-0.5b-instruct":       "qwen2.5:0.5b",
}


def _to_ollama_tag(base_model: str) -> str:
    """Convert HF id → Ollama tag if known; pass through otherwise.

    The Ollama daemon won't recognise ``meta-llama/Llama-3.2-3B-Instruct`` —
    it expects ``llama3.2:3b``. This map is the same one used in
    :mod:`utils.hf_model_id` (inverse direction)."""
    if not base_model:
        return ""
    key = base_model.strip().lower()
    return _HF_TO_OLLAMA.get(key, base_model)


__all__ = [
    "ForgeAnswer",
    "ForgeRoute",
    "TrackScore",
    "classify_prompt",
    "execute_route",
]
