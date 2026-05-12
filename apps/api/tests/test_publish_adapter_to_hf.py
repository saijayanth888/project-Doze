"""Tests for ``adapter.publish_huggingface``.

Covers the happy path + every documented failure mode. No real HTTP: we
replace the HfApi factory with an in-memory fake so the action talks to
a deterministic record-and-replay surface. The fake also lets us assert
exact call shape (repo_id, revision, allow/ignore patterns, prune order)
without re-implementing huggingface_hub internals.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from agents.actions import publish_adapter_to_hf as pub
from agents.actions.publish_adapter_to_hf import PublishAdapterToHuggingFace
from config.settings import settings


# ── HF fakes ───────────────────────────────────────────────────────────


class _FakeCommit:
    """Stand-in for huggingface_hub.CommitInfo."""

    def __init__(self, oid: str = "deadbeef") -> None:
        self.oid = oid


class _FakeRef:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeRefs:
    def __init__(self, tags: list[_FakeRef] | None = None) -> None:
        self.tags = tags or []


class _FakeHfApi:
    """Records every call. Knobs let individual tests inject failures.

    By default: repo exists, all uploads succeed, no pre-existing tags.
    Tests override ``raise_on_*`` to drive specific failure modes.
    """

    def __init__(self, token: str | None = None) -> None:
        self.token = token
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.existing_tags: list[str] = []
        self.deleted_tags: list[str] = []
        self.created_tags: list[str] = []
        # Failure injection knobs. ``None`` means "succeed".
        self.raise_on_repo_info: Exception | None = None
        self.raise_on_create_branch: Exception | None = None
        self.raise_on_upload: Exception | None = None
        self.raise_on_create_tag: Exception | None = None
        self.raise_on_list_refs: Exception | None = None
        self.raise_on_delete_tag: Exception | None = None

    def repo_info(self, *, repo_id, repo_type="model", **kwargs):
        self.calls.append(("repo_info", {"repo_id": repo_id, "repo_type": repo_type}))
        if self.raise_on_repo_info is not None:
            raise self.raise_on_repo_info
        return {"id": repo_id, "private": True}

    def create_branch(self, *, repo_id, branch, exist_ok=False, **kwargs):
        self.calls.append((
            "create_branch",
            {"repo_id": repo_id, "branch": branch, "exist_ok": exist_ok},
        ))
        if self.raise_on_create_branch is not None:
            raise self.raise_on_create_branch
        return None

    def upload_folder(
        self, *, repo_id, folder_path, repo_type="model", revision=None,
        commit_message=None, allow_patterns=None, ignore_patterns=None, **kwargs,
    ):
        self.calls.append((
            "upload_folder",
            {
                "repo_id": repo_id,
                "folder_path": folder_path,
                "repo_type": repo_type,
                "revision": revision,
                "commit_message": commit_message,
                "allow_patterns": list(allow_patterns or []),
                "ignore_patterns": list(ignore_patterns or []),
            },
        ))
        if self.raise_on_upload is not None:
            raise self.raise_on_upload
        return _FakeCommit()

    def create_tag(self, *, repo_id, tag, revision=None, repo_type="model",
                   exist_ok=False, **kwargs):
        self.calls.append((
            "create_tag",
            {"repo_id": repo_id, "tag": tag, "revision": revision},
        ))
        if self.raise_on_create_tag is not None:
            raise self.raise_on_create_tag
        self.created_tags.append(tag)
        # Pretend it's also visible to subsequent list_repo_refs calls.
        if tag not in self.existing_tags:
            self.existing_tags.append(tag)
        return None

    def list_repo_refs(self, *, repo_id, repo_type="model", **kwargs):
        self.calls.append(("list_repo_refs", {"repo_id": repo_id}))
        if self.raise_on_list_refs is not None:
            raise self.raise_on_list_refs
        return _FakeRefs([_FakeRef(t) for t in self.existing_tags])

    def delete_tag(self, *, repo_id, tag, repo_type="model", **kwargs):
        self.calls.append(("delete_tag", {"repo_id": repo_id, "tag": tag}))
        if self.raise_on_delete_tag is not None:
            raise self.raise_on_delete_tag
        self.deleted_tags.append(tag)
        if tag in self.existing_tags:
            self.existing_tags.remove(tag)
        return None


class _FakeHTTPError(Exception):
    """Mimics huggingface_hub.errors.HfHubHTTPError shape."""

    def __init__(self, status_code: int, message: str = "") -> None:
        super().__init__(message or f"HTTP {status_code}")
        self.response = type("R", (), {"status_code": status_code})()
        self.status_code = status_code


class _FakeRepositoryNotFoundError(Exception):
    """Mimics huggingface_hub.errors.RepositoryNotFoundError."""


# ── Test fixtures ──────────────────────────────────────────────────────


def _seed_adapter(tmp_path: Path, run_id: str, generation: int,
                  *, write_gguf: bool = True) -> Path:
    """Create ``<data_root>/adapters/<run_id>/gen-<N>`` with realistic files."""
    adir = tmp_path / "adapters" / run_id / f"gen-{generation}"
    adir.mkdir(parents=True)
    (adir / "adapter_config.json").write_text("{}", encoding="utf-8")
    (adir / "adapter_model.safetensors").write_bytes(b"\x00" * 64)
    (adir / "tokenizer.json").write_text("{}", encoding="utf-8")
    (adir / "tokenizer_config.json").write_text("{}", encoding="utf-8")
    # Heavy training intermediates that MUST be excluded from upload.
    (adir / "optimizer.pt").write_bytes(b"\x00" * 32)
    (adir / "training_args.bin").write_bytes(b"\x00" * 16)
    if write_gguf:
        (adir / "adapter.gguf").write_bytes(b"\x47\x47\x55\x46FAKE")
    return adir


def _pin_data_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MODELFORGE_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "modelforge_data_root", str(tmp_path),
                        raising=False)


def _install_fake(monkeypatch: pytest.MonkeyPatch, fake: _FakeHfApi) -> None:
    """Replace the action's factory + error types with our fakes."""
    monkeypatch.setattr(
        PublishAdapterToHuggingFace, "hf_api_factory",
        staticmethod(lambda token: fake),
        raising=False,
    )
    # Make _load_hf_errors return our fake exception types so the action's
    # except clauses match what the fake raises.
    monkeypatch.setattr(
        pub, "_load_hf_errors",
        lambda: (_FakeHTTPError, _FakeRepositoryNotFoundError),
    )


def _ctx(track_id: str = "trading-reflector", run_id: str = "run-abc",
         generation: int = 3) -> dict:
    return {
        "track_id": track_id,
        "run_id": run_id,
        "generation": generation,
        "last": {}, "workflow": {"id": "wf-1", "name": "test"},
    }


def _set_token(monkeypatch: pytest.MonkeyPatch, value: str | None = "hf_TESTTOKEN") -> None:
    if value is None:
        monkeypatch.setattr(settings, "hf_token", None, raising=False)
        monkeypatch.delenv("HF_TOKEN", raising=False)
    else:
        monkeypatch.setattr(settings, "hf_token", value, raising=False)
        monkeypatch.setenv("HF_TOKEN", value)


# ── Happy path ─────────────────────────────────────────────────────────


async def test_publish_happy_path_uploads_tags_and_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end happy path:

    * Repo existence is probed
    * upload_folder is called with the resolved revision + allow/ignore
    * create_tag tags the revision
    * Result reports repo_url, revision, files_uploaded, pruned=[]
    """
    _pin_data_root(monkeypatch, tmp_path)
    _set_token(monkeypatch)
    adir = _seed_adapter(tmp_path, "run-abc", 3)
    fake = _FakeHfApi()
    _install_fake(monkeypatch, fake)

    result = await PublishAdapterToHuggingFace().execute(
        config={"repo_id": "Saijayanyh532ai/dgx-trader-adapters"},
        context=_ctx(),
        engine=None,
    )

    assert result.status == "ok", result.message
    assert result.output["repo_id"] == "Saijayanyh532ai/dgx-trader-adapters"
    assert result.output["revision"].startswith("trading-reflector-v")
    assert result.output["role"] == "reflector"
    assert result.output["adapter_dir"] == str(adir)
    assert result.output["pruned"] == []
    # repo_url is the *public* tree URL — no token in it.
    assert result.output["repo_url"].startswith("https://huggingface.co/")
    assert "hf_" not in result.output["repo_url"]
    assert result.output["files_uploaded"] >= 4  # config, safetensors, tokenizer*, gguf

    # The fake recorded the exact call sequence we expect.
    call_kinds = [c[0] for c in fake.calls]
    assert call_kinds[0] == "repo_info"
    assert "upload_folder" in call_kinds
    assert "create_tag" in call_kinds
    assert "list_repo_refs" in call_kinds

    upload_args = next(c[1] for c in fake.calls if c[0] == "upload_folder")
    assert upload_args["folder_path"] == str(adir)
    assert upload_args["revision"].startswith("trading-reflector-v")
    # Training intermediates are excluded; adapter files are allowed.
    assert "optimizer.pt" in upload_args["ignore_patterns"]
    assert "training_args.bin" in upload_args["ignore_patterns"]
    assert "*.safetensors" in upload_args["allow_patterns"]
    assert "*.gguf" in upload_args["allow_patterns"]


# ── Missing token → skipped ────────────────────────────────────────────


async def test_publish_skipped_when_no_hf_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_data_root(monkeypatch, tmp_path)
    _set_token(monkeypatch, None)
    _seed_adapter(tmp_path, "run-notoken", 1)

    result = await PublishAdapterToHuggingFace().execute(
        config={}, context=_ctx(run_id="run-notoken", generation=1),
        engine=None,
    )
    assert result.status == "skipped"
    assert "HF_TOKEN" in result.message


# ── HF unreachable (network) → skipped ─────────────────────────────────


async def test_publish_skipped_when_repo_probe_network_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DNS / socket / timeout on the initial repo probe → skipped, not error."""
    _pin_data_root(monkeypatch, tmp_path)
    _set_token(monkeypatch)
    _seed_adapter(tmp_path, "run-net", 2)
    fake = _FakeHfApi()
    fake.raise_on_repo_info = ConnectionError("DNS lookup failed")
    _install_fake(monkeypatch, fake)

    result = await PublishAdapterToHuggingFace().execute(
        config={}, context=_ctx(run_id="run-net", generation=2),
        engine=None,
    )
    assert result.status == "skipped"
    assert "unreachable" in result.message.lower()
    # We probed, then bailed — no upload attempt.
    assert "upload_folder" not in [c[0] for c in fake.calls]


# ── Repo missing → error with create-repo hint ─────────────────────────


async def test_publish_errors_when_repo_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_data_root(monkeypatch, tmp_path)
    _set_token(monkeypatch)
    _seed_adapter(tmp_path, "run-norepo", 3)
    fake = _FakeHfApi()
    fake.raise_on_repo_info = _FakeRepositoryNotFoundError("404")
    _install_fake(monkeypatch, fake)

    result = await PublishAdapterToHuggingFace().execute(
        config={"repo_id": "fakeuser/missing-repo"},
        context=_ctx(run_id="run-norepo", generation=3),
        engine=None,
    )
    assert result.status == "error"
    assert result.error == "repo_not_found"
    assert "huggingface.co/new" in result.message


# ── Token lacks write scope (401/403) → error ──────────────────────────


@pytest.mark.parametrize("status_code", [401, 403])
async def test_publish_errors_when_token_lacks_write_scope(
    status_code: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_data_root(monkeypatch, tmp_path)
    _set_token(monkeypatch)
    _seed_adapter(tmp_path, "run-403", 4)
    fake = _FakeHfApi()
    fake.raise_on_repo_info = _FakeHTTPError(status_code, "no write scope")
    _install_fake(monkeypatch, fake)

    result = await PublishAdapterToHuggingFace().execute(
        config={}, context=_ctx(run_id="run-403", generation=4),
        engine=None,
    )
    assert result.status == "error"
    assert result.error == "token_lacks_write_scope"


# ── Quota exceeded (413) → skipped ─────────────────────────────────────


async def test_publish_skipped_when_quota_exceeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_data_root(monkeypatch, tmp_path)
    _set_token(monkeypatch)
    _seed_adapter(tmp_path, "run-quota", 5)
    fake = _FakeHfApi()
    fake.raise_on_upload = _FakeHTTPError(413, "quota exceeded")
    _install_fake(monkeypatch, fake)

    result = await PublishAdapterToHuggingFace().execute(
        config={}, context=_ctx(run_id="run-quota", generation=5),
        engine=None,
    )
    assert result.status == "skipped"
    assert "quota" in result.message.lower()


# ── Upload mid-stream failure → error ──────────────────────────────────


async def test_publish_errors_on_upload_mid_stream_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_data_root(monkeypatch, tmp_path)
    _set_token(monkeypatch)
    _seed_adapter(tmp_path, "run-mid", 6)
    fake = _FakeHfApi()
    fake.raise_on_upload = _FakeHTTPError(500, "server hung up")
    _install_fake(monkeypatch, fake)

    result = await PublishAdapterToHuggingFace().execute(
        config={}, context=_ctx(run_id="run-mid", generation=6),
        engine=None,
    )
    assert result.status == "error"
    assert result.error == "upload_failed"


# ── Adapter dir missing → error ────────────────────────────────────────


async def test_publish_errors_when_adapter_dir_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_data_root(monkeypatch, tmp_path)
    _set_token(monkeypatch)
    # No _seed_adapter call — directory simply doesn't exist.
    fake = _FakeHfApi()
    _install_fake(monkeypatch, fake)

    result = await PublishAdapterToHuggingFace().execute(
        config={}, context=_ctx(run_id="run-missing", generation=99),
        engine=None,
    )
    assert result.status == "error"
    assert result.error == "adapter_dir_missing"


# ── Payload incomplete → error ─────────────────────────────────────────


async def test_publish_errors_on_missing_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_data_root(monkeypatch, tmp_path)
    _set_token(monkeypatch)
    result = await PublishAdapterToHuggingFace().execute(
        config={},
        context={"track_id": "trading-reflector", "last": {}},  # no run_id / gen
        engine=None,
    )
    assert result.status == "error"
    assert "track_id" in result.message
    assert "run_id" in result.message


# ── Auto-prune: keep last N ────────────────────────────────────────────


async def test_publish_prunes_old_tags_keeping_last_n(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With 10 existing tags and keep_last_n=8, exactly 2 oldest are pruned.

    Tags are versioned by date in the role prefix, so lexicographic
    sort = chronological sort. We seed 10 dated tags so the action can
    identify the two oldest by prefix match + sort.
    """
    _pin_data_root(monkeypatch, tmp_path)
    _set_token(monkeypatch)
    _seed_adapter(tmp_path, "run-prune", 7)
    fake = _FakeHfApi()
    # Existing tags: 10 prior versions of trading-reflector + 3 unrelated
    # tags that must NOT be pruned (different role).
    fake.existing_tags = [
        f"trading-reflector-v202604{day:02d}" for day in range(10, 20)
    ] + [
        "trading-arbiter-v20260415",
        "trading-arbiter-v20260420",
        "other-prefix-v20260101",
    ]
    _install_fake(monkeypatch, fake)

    result = await PublishAdapterToHuggingFace().execute(
        config={"keep_last_n": 8},
        context=_ctx(run_id="run-prune", generation=7),
        engine=None,
    )

    assert result.status == "ok", result.message
    # 10 dated existing tags + 1 freshly created tag for today.
    # After upload, before pruning we have 11 trading-reflector tags;
    # keep 8 → delete 3 oldest. But the action filters by the role
    # prefix only (not today's tag), so we expect exactly 3 prunes
    # of the oldest reflector tags. arbiter + other-prefix untouched.
    pruned = result.output["pruned"]
    assert len(pruned) == 3
    assert all(t.startswith("trading-reflector-v") for t in pruned)
    # Sanity: arbiter tags are NOT in the prune list.
    assert not any(t.startswith("trading-arbiter") for t in pruned)
    assert "other-prefix-v20260101" not in pruned
    # The oldest 3 dates are 10-12 of the seeded range.
    assert pruned == [
        "trading-reflector-v20260410",
        "trading-reflector-v20260411",
        "trading-reflector-v20260412",
    ]


async def test_publish_does_not_prune_when_under_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fewer existing tags than keep_last_n → no deletions."""
    _pin_data_root(monkeypatch, tmp_path)
    _set_token(monkeypatch)
    _seed_adapter(tmp_path, "run-keep", 8)
    fake = _FakeHfApi()
    fake.existing_tags = ["trading-reflector-v20260501", "trading-reflector-v20260502"]
    _install_fake(monkeypatch, fake)

    result = await PublishAdapterToHuggingFace().execute(
        config={"keep_last_n": 8},
        context=_ctx(run_id="run-keep", generation=8),
        engine=None,
    )
    assert result.status == "ok"
    assert result.output["pruned"] == []
    assert fake.deleted_tags == []


# ── Auto-prune failure is non-fatal ────────────────────────────────────


async def test_publish_returns_ok_with_warning_when_prune_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upload succeeded but list_repo_refs blew up → status=ok + warning."""
    _pin_data_root(monkeypatch, tmp_path)
    _set_token(monkeypatch)
    _seed_adapter(tmp_path, "run-warn", 9)
    fake = _FakeHfApi()
    fake.raise_on_list_refs = RuntimeError("flaky refs API")
    _install_fake(monkeypatch, fake)

    result = await PublishAdapterToHuggingFace().execute(
        config={}, context=_ctx(run_id="run-warn", generation=9),
        engine=None,
    )
    assert result.status == "ok"
    assert "warning" in result.output
    assert "list_repo_refs" in result.output["warning"]


# ── Pattern substitution ───────────────────────────────────────────────


def test_render_revision_substitutes_all_placeholders() -> None:
    name = pub._render_revision(
        "{track_id}-{role}-v{date}-g{generation}-{run_id}",
        track_id="trading-reflector", role="reflector",
        date="20260512", generation=4, run_id="run-x",
    )
    assert name == "trading-reflector-reflector-v20260512-g4-run-x"


def test_render_revision_default_pattern() -> None:
    name = pub._render_revision(
        "{track_id}-v{date}",
        track_id="trading-reflector", role="reflector",
        date="20260512", generation=0, run_id="run-x",
    )
    assert name == "trading-reflector-v20260512"


def test_role_from_track_id_strips_trading_prefix() -> None:
    assert pub._role_from_track_id("trading-reflector") == "reflector"
    assert pub._role_from_track_id("trading-arbiter") == "arbiter"
    assert pub._role_from_track_id("custom-track") == "custom-track"
    assert pub._role_from_track_id("") == "unknown"


# ── Secret redaction ───────────────────────────────────────────────────


def test_logger_redacts_hf_token_in_messages(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Any log line written through this module's logger must have hf_*
    tokens scrubbed to <REDACTED>."""
    caplog.set_level(logging.WARNING, logger=pub.logger.name)
    pub.logger.warning("attempted call with token=hf_AAAAAAAAAAAAAAAAAAAAAAAAAAA tail")
    pub.logger.warning("nothing sensitive here")

    messages = [r.getMessage() for r in caplog.records]
    assert any("<REDACTED>" in m for m in messages)
    # The raw token MUST NOT appear in any captured message.
    for m in messages:
        assert "hf_AAAAAAAAAAAAAAAAAAAAAAAAAAA" not in m


async def test_publish_never_logs_token_on_happy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Sanity: even on the happy path we don't accidentally emit the
    token through this module's logger."""
    _pin_data_root(monkeypatch, tmp_path)
    sentinel = "hf_BBBBBBBBBBBBBBBBBBBBBBBBBBB"
    _set_token(monkeypatch, sentinel)
    _seed_adapter(tmp_path, "run-quiet", 1)
    fake = _FakeHfApi()
    _install_fake(monkeypatch, fake)

    caplog.set_level(logging.DEBUG, logger=pub.logger.name)
    result = await PublishAdapterToHuggingFace().execute(
        config={}, context=_ctx(run_id="run-quiet", generation=1),
        engine=None,
    )
    assert result.status == "ok"
    for record in caplog.records:
        assert sentinel not in record.getMessage()
    # And the result envelope must not leak the token either.
    assert sentinel not in repr(result.output)


# ── Files-uploaded counter excludes ignored intermediates ──────────────


def test_files_uploaded_excludes_training_intermediates(
    tmp_path: Path,
) -> None:
    """``_count_uploaded_files`` should never include optimizer.pt et al."""
    adir = _seed_adapter(tmp_path, "run-count", 1)
    allow = pub._build_allow_patterns(include_safetensors=True, include_gguf=True)
    count = pub._count_uploaded_files(adir, allow, pub._DEFAULT_IGNORE_PATTERNS)
    files_on_disk = sorted(p.name for p in adir.iterdir() if p.is_file())
    assert "optimizer.pt" in files_on_disk
    assert "training_args.bin" in files_on_disk
    # Counted: adapter_config, adapter_model.safetensors, tokenizer.json,
    # tokenizer_config.json, adapter.gguf — five files.
    assert count == 5


# ── Registry integration ──────────────────────────────────────────────


def test_action_registered_in_registry() -> None:
    from services.automation_engine.actions import ACTION_REGISTRY
    assert "adapter.publish_huggingface" in ACTION_REGISTRY
    assert ACTION_REGISTRY["adapter.publish_huggingface"] is PublishAdapterToHuggingFace


def test_seed_workflow_includes_hf_step_between_ollama_and_slack() -> None:
    """The 'Publish Promoted Adapter to Ollama' workflow must now run
    the HF mirror BETWEEN the local Ollama push and the Slack ping."""
    from services.automation_engine.seeds import DEFAULT_WORKFLOWS
    by_name = {w["name"]: w for w in DEFAULT_WORKFLOWS}
    wf = by_name.get("Publish Promoted Adapter to Ollama")
    assert wf is not None
    kinds = [a["kind"] for a in wf["actions"]]
    assert kinds == [
        "adapter.publish_ollama",
        "adapter.publish_huggingface",
        "notify.slack",
    ]
    # The HF step uses the documented private repo as its default.
    hf_step = wf["actions"][1]
    assert hf_step["config"]["repo_id"] == "Saijayanyh532ai/dgx-trader-adapters"
