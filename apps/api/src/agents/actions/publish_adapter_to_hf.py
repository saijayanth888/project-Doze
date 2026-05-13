"""``adapter.publish_huggingface`` — mirror a promoted LoRA adapter to a
private Hugging Face Hub repository.

Sibling of ``adapter.publish_ollama``. Where the Ollama publisher streams
a GGUF blob into the local Ollama server (zero-network, host-only), THIS
action does the opposite: it pushes the entire on-disk adapter directory
(safetensors + tokenizer + adapter_config + GGUF if present) to a
pre-existing private HF Hub repo so the trading bot has a durable,
off-host backup it can pull from anywhere.

The two actions are wired in sequence under the same workflow so a
``track.promoted`` event fans out to:

    adapter.publish_ollama        # local, fast, zero-network
    → adapter.publish_huggingface # network mirror, durable backup
    → notify.slack                # one ping after both land

Design rules (operator-friendly degradation):

* NO HEAVY CONTAINERS. NO MODEL LOADS. Pure HTTP push via
  ``huggingface_hub.HfApi``.
* The HF Hub is optional infrastructure — if it's unreachable, the token
  is missing, or quota is exceeded, the action returns ``skipped`` (NOT
  ``error``) so the workflow run shows up as skipped rather than red.
  Adapters remain on disk; the operator can re-trigger when HF is back.
* Genuinely structural problems (repo doesn't exist, token has no write
  scope, upload failed mid-stream) DO return ``error`` because they
  require operator intervention.
* The HF_TOKEN value MUST NEVER appear in any log line. We redact at
  the source via a logging filter installed on this module's logger,
  and also avoid passing the token into f-strings or repr()s.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, Callable

from config.settings import settings
from services.automation_engine.actions import Action, ActionResult

logger = logging.getLogger("modelforge.automation.actions.publish_adapter_to_hf")


# ── Secret redaction ───────────────────────────────────────────────────


class _RedactHfTokenFilter(logging.Filter):
    """Strip any ``hf_*`` token-looking substring out of every log record.

    Two layers of paranoia:

    1. We never construct log messages that include the token.
    2. If something slips through (a third-party library, a stray repr),
       this filter rewrites the rendered message before it's emitted.

    The pattern matches the Hugging Face token format (``hf_`` followed
    by 30-40 base62-ish characters) which is the only secret this module
    is meant to handle.
    """

    _TOKEN_RE = re.compile(r"hf_[A-Za-z0-9]{20,}")

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover — defensive
            return True
        if self._TOKEN_RE.search(msg):
            record.msg = self._TOKEN_RE.sub("<REDACTED>", msg)
            record.args = ()
        return True


# Install once at import time so every log line emitted by this module
# is sanitized — even ones produced during the import side-effect path.
if not any(isinstance(f, _RedactHfTokenFilter) for f in logger.filters):
    logger.addFilter(_RedactHfTokenFilter())


# ── Helpers ────────────────────────────────────────────────────────────


def _role_from_track_id(track_id: str) -> str:
    """``trading-reflector`` → ``reflector``; preserves non-trading IDs."""
    track_id = str(track_id or "").strip()
    if track_id.startswith("trading-"):
        return track_id[len("trading-") :]
    return track_id or "unknown"


def _adapter_dir(run_id: str, generation: int) -> Path:
    """``<data_root>/adapters/<run_id>/gen-<N>`` — no existence check."""
    data_root = settings.resolve_data_root()
    return data_root / "adapters" / str(run_id) / f"gen-{int(generation)}"


def _render_revision(
    pattern: str,
    *,
    track_id: str,
    role: str,
    date: str,
    generation: int,
    run_id: str,
) -> str:
    """Substitute the placeholders the schema documents.

    Accepts both the public-facing ``{track_id}`` token AND the
    convenience tokens shared with the Ollama publisher.
    """
    return (
        (pattern or "")
        .replace("{track_id}", track_id)
        .replace("{role}", role)
        .replace("{date}", date)
        .replace("{generation}", str(generation))
        .replace("{run_id}", str(run_id))
    )


# Files we never want to upload — heavy training intermediates that
# bloat the repo without helping inference.
_DEFAULT_IGNORE_PATTERNS: list[str] = [
    "optimizer.pt",
    "training_args.bin",
    "scheduler.pt",
    "rng_state.pth",
    "trainer_state.json",
    "checkpoint-*/**",
    "global_step*/**",
    "*.tmp",
    ".DS_Store",
]


def _build_allow_patterns(
    *, include_safetensors: bool, include_gguf: bool,
) -> list[str]:
    """Whitelist patterns based on the schema toggles."""
    allow: list[str] = [
        "adapter_config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "tokenizer.model",
        "special_tokens_map.json",
        "added_tokens.json",
        "chat_template.jinja",
        "README.md",
    ]
    if include_safetensors:
        allow.extend(["adapter_model.safetensors", "*.safetensors"])
    if include_gguf:
        allow.append("*.gguf")
    return allow


# ── HF Hub client factory (test seam) ──────────────────────────────────


def _default_hf_api_factory(token: str | None):  # pragma: no cover
    """Real ``HfApi()`` constructor. Tests replace this via the
    ``Action.hf_api_factory`` attribute so we never reach the network in
    unit tests and we never need to mock the module-level import.
    """
    from huggingface_hub import HfApi
    return HfApi(token=token)


# Lazy import of the error types — kept inside the action so the module
# imports cleanly even on hosts where ``huggingface_hub`` isn't installed
# (the action will degrade to ``skipped`` at execute time).
def _load_hf_errors():
    try:
        from huggingface_hub.errors import (
            HfHubHTTPError,
            RepositoryNotFoundError,
        )
        return HfHubHTTPError, RepositoryNotFoundError
    except Exception:  # pragma: no cover — defensive
        return Exception, Exception


# ── Action ─────────────────────────────────────────────────────────────


class PublishAdapterToHuggingFace(Action):
    """Mirror a promoted LoRA adapter directory to private HF Hub."""

    kind = "adapter.publish_huggingface"
    label = "Publish adapter to Hugging Face Hub"
    description = (
        "Push the on-disk adapter (safetensors + tokenizer + "
        "adapter_config + optional GGUF) to a private HF Hub repo, tag "
        "the commit with a versioned revision, and prune older versions "
        "past the retention window. Wire this AFTER adapter.publish_ollama "
        "on the track.promoted workflow."
    )
    schema = [
        {
            "name": "repo_id", "type": "string",
            "label": "HF repo id", "default": "Saijayanyh532ai/dgx-trader-adapters",
            "help": "Pre-existing private model-type repo. Create at "
                    "https://huggingface.co/new before enabling.",
        },
        {
            "name": "revision_pattern", "type": "string",
            "label": "Revision/tag pattern",
            "default": "{track_id}-v{date}",
            "help": "Placeholders: {track_id}, {role}, {date} (UTC "
                    "YYYYMMDD), {generation}, {run_id}.",
        },
        {
            "name": "keep_last_n", "type": "number",
            "label": "Versions to retain per role",
            "default": 8,
            "help": "Older tags matching this role's pattern are pruned.",
        },
        {
            "name": "include_gguf", "type": "boolean",
            "label": "Include *.gguf files", "default": True,
        },
        {
            "name": "include_safetensors", "type": "boolean",
            "label": "Include *.safetensors files", "default": True,
        },
    ]

    # Test seam. Production resolves the real ``HfApi`` factory; tests
    # assign a fake here to drive the action without hitting the network.
    hf_api_factory: Callable[[str | None], Any] = staticmethod(_default_hf_api_factory)

    # ── execute ──────────────────────────────────────────────────────

    async def execute(self, *, config, context, engine):  # noqa: ARG002
        # 1) Payload sanity.
        track_id = str(context.get("track_id") or "").strip()
        run_id = str(context.get("run_id") or "").strip()
        generation_raw = context.get("generation")
        try:
            generation = int(generation_raw) if generation_raw is not None else None
        except (TypeError, ValueError):
            generation = None

        if not track_id or not run_id or generation is None:
            return ActionResult(
                status="error",
                error="missing payload",
                message=(
                    "track.promoted payload incomplete -- need track_id, "
                    f"run_id, generation; got {track_id!r}/{run_id!r}/"
                    f"{generation_raw!r}"
                ),
            )

        # 2) Adapter dir on disk.
        adapter_dir = _adapter_dir(run_id, int(generation))
        if not adapter_dir.is_dir():
            return ActionResult(
                status="error",
                error="adapter_dir_missing",
                message=f"Adapter directory not on disk: {adapter_dir}",
            )

        # 3) HF token — graceful skip if absent.
        token = (settings.hf_token or os.environ.get("HF_TOKEN") or "").strip() or None
        if not token:
            return ActionResult(
                status="skipped",
                message="no HF_TOKEN -- set in model-forge .env",
                output={"adapter_dir": str(adapter_dir)},
            )

        # 4) Compose names.
        repo_id = str(config.get("repo_id") or "Saijayanyh532ai/dgx-trader-adapters").strip()
        role = _role_from_track_id(track_id)
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        revision = _render_revision(
            str(config.get("revision_pattern") or "{track_id}-v{date}"),
            track_id=track_id, role=role, date=date_str,
            generation=int(generation), run_id=run_id,
        )
        try:
            keep_last_n = int(config.get("keep_last_n") or 8)
        except (TypeError, ValueError):
            keep_last_n = 8
        include_gguf = bool(config.get("include_gguf", True))
        include_safetensors = bool(config.get("include_safetensors", True))

        allow_patterns = _build_allow_patterns(
            include_safetensors=include_safetensors,
            include_gguf=include_gguf,
        )

        # 5) Build the HfApi client. The factory is a class attribute so
        # tests can swap it for an in-memory fake without monkeypatching
        # the huggingface_hub import path.
        try:
            api = type(self).hf_api_factory(token)
        except ImportError as exc:
            return ActionResult(
                status="skipped",
                message=(
                    "huggingface_hub not importable -- adapter remains "
                    f"local. ({exc})"
                ),
                output={"adapter_dir": str(adapter_dir)},
            )

        HfHubHTTPError, RepositoryNotFoundError = _load_hf_errors()

        # 6) Verify the repo exists (cheap GET). Distinguish 404 (operator
        # must create) from 401/403 (token has no scope) from network
        # errors (HF is just down).
        # All ``api.*`` calls below are synchronous huggingface_hub HTTP
        # operations. The upload_folder call in particular streams the
        # entire 3-4 GB safetensors blob over the network and can hold the
        # connection open for 20+ minutes. Running that on the API's
        # asyncio event loop bricks every other endpoint until the upload
        # completes — Docker marks the container unhealthy, /api/forge/tracks
        # times out from the dashboard's 3.5s probe, and operators see
        # "model forge is down" even though the process is alive. Wrap all
        # blocking HF calls in asyncio.to_thread so they run on a worker
        # thread and the event loop stays free to service /api/system/status,
        # /api/forge/tracks, /api/evolve/*, etc.
        try:
            await asyncio.to_thread(
                partial(api.repo_info, repo_id=repo_id, repo_type="model")
            )
        except RepositoryNotFoundError:
            return ActionResult(
                status="error",
                error="repo_not_found",
                message=(
                    f"HF repo not found: {repo_id} -- create at "
                    "https://huggingface.co/new (private, model type)"
                ),
                output={"repo_id": repo_id, "adapter_dir": str(adapter_dir)},
            )
        except HfHubHTTPError as exc:
            code = _http_status_code(exc)
            if code in (401, 403):
                return ActionResult(
                    status="error",
                    error="token_lacks_write_scope",
                    message=(
                        f"HF token rejected (HTTP {code}) on {repo_id} -- "
                        "regenerate a token with write scope"
                    ),
                    output={"repo_id": repo_id, "http_status": code},
                )
            # Any other HTTP error here is treated as transient.
            return ActionResult(
                status="skipped",
                message=(
                    f"HF unreachable on repo probe (HTTP {code}) -- adapter "
                    "remains local"
                ),
                output={"repo_id": repo_id, "adapter_dir": str(adapter_dir)},
            )
        except Exception as exc:
            # Network / DNS / timeout / unexpected. Skip, don't fail.
            return ActionResult(
                status="skipped",
                message=(
                    "HF unreachable -- adapter remains local "
                    f"({exc.__class__.__name__})"
                ),
                output={"repo_id": repo_id, "adapter_dir": str(adapter_dir)},
            )

        # 7) Upload the folder onto a branch named after the revision.
        # huggingface_hub creates the branch on first push if needed via
        # create_branch; we do that explicitly so a partial upload still
        # produces a ref we can clean up.
        try:
            await asyncio.to_thread(
                partial(api.create_branch,
                        repo_id=repo_id, branch=revision, exist_ok=True)
            )
        except AttributeError:
            # Older API lacks create_branch — upload_folder will create
            # the revision implicitly. Non-fatal.
            pass
        except HfHubHTTPError as exc:
            code = _http_status_code(exc)
            if code in (401, 403):
                return ActionResult(
                    status="error",
                    error="token_lacks_write_scope",
                    message=f"HF token rejected creating branch (HTTP {code})",
                    output={"repo_id": repo_id, "revision": revision},
                )
            # Other HTTP errors during branch create are typically benign
            # (branch already exists is the common one) — proceed.
            logger.info(
                "[publish-hf] create_branch HTTP %s on %s/%s; continuing",
                code, repo_id, revision,
            )

        try:
            # The heavyweight call — streams 3-4 GB to HF Hub. Must run
            # in a worker thread or the event loop hangs for the entire
            # upload duration.
            commit_info = await asyncio.to_thread(
                partial(
                    api.upload_folder,
                    repo_id=repo_id,
                    folder_path=str(adapter_dir),
                    repo_type="model",
                    revision=revision,
                    commit_message=f"Promote {track_id} gen-{generation} ({run_id})",
                    allow_patterns=allow_patterns,
                    ignore_patterns=_DEFAULT_IGNORE_PATTERNS,
                )
            )
        except HfHubHTTPError as exc:
            code = _http_status_code(exc)
            if code in (401, 403):
                return ActionResult(
                    status="error",
                    error="token_lacks_write_scope",
                    message=f"HF upload rejected (HTTP {code})",
                    output={"repo_id": repo_id, "revision": revision},
                )
            if code == 413:
                return ActionResult(
                    status="skipped",
                    message=(
                        "hf_quota_exceeded -- increase plan or prune more "
                        "aggressively"
                    ),
                    output={"repo_id": repo_id, "revision": revision},
                )
            return ActionResult(
                status="error",
                error="upload_failed",
                message=f"upload_failed -- HTTP {code}: {str(exc)[:200]}",
                output={"repo_id": repo_id, "revision": revision},
            )
        except OSError as exc:
            return ActionResult(
                status="error",
                error="upload_failed",
                message=f"upload_failed -- last_file=<local IO> ({exc})",
                output={"repo_id": repo_id, "revision": revision},
            )
        except Exception as exc:
            # Mid-stream connection drop / unexpected library error.
            return ActionResult(
                status="error",
                error="upload_failed",
                message=(
                    f"upload_failed -- last_file=<unknown> "
                    f"({exc.__class__.__name__}: {str(exc)[:160]})"
                ),
                output={"repo_id": repo_id, "revision": revision},
            )

        # 8) Tag the commit so it survives a future branch rename.
        tag_warning: str | None = None
        try:
            await asyncio.to_thread(
                partial(
                    api.create_tag,
                    repo_id=repo_id, tag=revision,
                    revision=revision, repo_type="model",
                    exist_ok=True,
                )
            )
        except HfHubHTTPError as exc:
            tag_warning = f"tag_create_failed: HTTP {_http_status_code(exc)}"
            logger.warning("[publish-hf] %s", tag_warning)
        except Exception as exc:
            tag_warning = f"tag_create_failed: {exc.__class__.__name__}"
            logger.warning("[publish-hf] %s", tag_warning)

        # 9) Auto-prune older versions matching this role's prefix.
        pruned: list[str] = []
        prune_warning: str | None = None
        prefix = _render_revision(
            str(config.get("revision_pattern") or "{track_id}-v{date}").split("{date}")[0],
            track_id=track_id, role=role, date="", generation=int(generation),
            run_id=run_id,
        )
        try:
            refs = await asyncio.to_thread(
                partial(api.list_repo_refs, repo_id=repo_id, repo_type="model")
            )
            existing_tags = sorted(
                t.name for t in (refs.tags or [])
                if prefix and t.name.startswith(prefix)
            )
            if keep_last_n > 0 and len(existing_tags) > keep_last_n:
                to_delete = existing_tags[:-keep_last_n]
                for tag in to_delete:
                    if tag == revision:
                        continue  # never prune the version we just made
                    try:
                        await asyncio.to_thread(
                            partial(api.delete_tag,
                                    repo_id=repo_id, tag=tag, repo_type="model")
                        )
                        pruned.append(tag)
                    except Exception as exc:
                        prune_warning = (
                            f"delete_tag failed for {tag}: "
                            f"{exc.__class__.__name__}"
                        )
                        logger.warning("[publish-hf] %s", prune_warning)
                        break
        except Exception as exc:
            prune_warning = (
                f"list_repo_refs failed: {exc.__class__.__name__} -- "
                "upload succeeded; prune skipped"
            )
            logger.warning("[publish-hf] %s", prune_warning)

        # 10) Count files actually staged for upload (allow ∩ on-disk
        # minus ignore). Best-effort — failure is non-fatal.
        files_uploaded = _count_uploaded_files(
            adapter_dir, allow_patterns, _DEFAULT_IGNORE_PATTERNS,
        )

        repo_url = f"https://huggingface.co/{repo_id}/tree/{revision}"
        commit_oid = getattr(commit_info, "oid", None) or getattr(
            commit_info, "commit_oid", None,
        )

        output: dict[str, Any] = {
            "repo_id": repo_id,
            "repo_url": repo_url,
            "revision": revision,
            "files_uploaded": files_uploaded,
            "pruned": pruned,
            "track_id": track_id,
            "role": role,
            "run_id": run_id,
            "generation": int(generation),
            "adapter_dir": str(adapter_dir),
            "commit_oid": commit_oid,
        }
        warning_bits = [w for w in (tag_warning, prune_warning) if w]
        if warning_bits:
            output["warning"] = "; ".join(warning_bits)
        return ActionResult(
            status="ok",
            message=(
                f"Mirrored to HF: {repo_id}@{revision} "
                f"({files_uploaded} files, pruned {len(pruned)})"
            ),
            output=output,
        )


# ── Module-level utilities ─────────────────────────────────────────────


def _http_status_code(exc: Exception) -> int:
    """Best-effort extraction of an HTTP status code from an HfHubHTTPError.

    huggingface_hub exposes ``.response.status_code`` on its HTTPError
    subclass; older versions exposed ``.status_code`` directly. We try
    both and fall back to 0 so callers can compare against the table.
    """
    resp = getattr(exc, "response", None)
    if resp is not None:
        code = getattr(resp, "status_code", None)
        if code is not None:
            try:
                return int(code)
            except (TypeError, ValueError):
                pass
    code = getattr(exc, "status_code", None)
    if code is not None:
        try:
            return int(code)
        except (TypeError, ValueError):
            pass
    return 0


def _count_uploaded_files(
    folder: Path, allow_patterns: list[str], ignore_patterns: list[str],
) -> int:
    """Walk the folder and count files matching ``allow_patterns`` and
    not matching ``ignore_patterns``. Used purely for the result trace —
    if anything goes wrong we just return 0 so we don't poison the
    happy-path return.
    """
    from fnmatch import fnmatch

    try:
        count = 0
        for path in folder.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(folder).as_posix()
            if not any(fnmatch(rel, p) or fnmatch(path.name, p)
                       for p in allow_patterns):
                continue
            if any(fnmatch(rel, p) or fnmatch(path.name, p)
                   for p in ignore_patterns):
                continue
            count += 1
        return count
    except Exception:  # pragma: no cover — non-fatal
        return 0


# ── Self-registration ──────────────────────────────────────────────────

try:  # pragma: no cover — the import side-effect IS the test
    from services.automation_engine.actions import register_action
    register_action(PublishAdapterToHuggingFace)
except Exception as _exc:  # pragma: no cover
    logger.warning("[publish-hf] self-registration failed: %s", _exc)


__all__ = ["PublishAdapterToHuggingFace"]
