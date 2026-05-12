"""Tests for ``adapter.publish_ollama``.

Covers the happy path + every documented failure mode. No real HTTP and
no real subprocess: we monkeypatch ``httpx.AsyncClient`` to use a
``MockTransport`` so we can assert exact request bodies, and the
GGUF-conversion subprocess is short-circuited by writing a .gguf into
the adapter dir before the action runs.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agents.actions import publish_adapter_to_ollama as pub
from agents.actions.publish_adapter_to_ollama import PublishAdapterToOllama
from config.settings import settings


# ── helpers ───────────────────────────────────────────────────────────


def _seed_adapter(tmp_path: Path, run_id: str, generation: int, *,
                  write_gguf: bool = True, gguf_bytes: bytes = b"\x47\x47\x55\x46FAKE",
                  ) -> Path:
    """Create ``<data_root>/adapters/<run_id>/gen-<N>`` with an optional
    fake GGUF file. The bytes don't have to be a real GGUF -- the action
    treats the file as an opaque blob."""
    adir = tmp_path / "adapters" / run_id / f"gen-{generation}"
    adir.mkdir(parents=True)
    (adir / "adapter_config.json").write_text("{}", encoding="utf-8")
    (adir / "adapter_model.safetensors").write_bytes(b"\x00" * 16)
    if write_gguf:
        (adir / "adapter.gguf").write_bytes(gguf_bytes)
    return adir


class _Recorder:
    """Captures every ``httpx`` request the action makes so the test can
    assert request shape without re-implementing httpx internals."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._respond(request)

    def _respond(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        method = request.method
        # /api/tags ping -> models list (any non-error body works)
        if method == "GET" and url.endswith("/api/tags"):
            return httpx.Response(200, json={"models": []})
        # PUT /api/blobs/sha256:... -> 201 on first upload
        if method == "PUT" and "/api/blobs/sha256:" in url:
            return httpx.Response(201, text="")
        # POST /api/create -> 200
        if method == "POST" and url.endswith("/api/create"):
            return httpx.Response(200, json={"status": "success"})
        # DELETE /api/delete -> 404 (alias didn't exist yet) or 200
        if method == "DELETE" and url.endswith("/api/delete"):
            return httpx.Response(404, text="not found")
        # POST /api/copy -> 200
        if method == "POST" and url.endswith("/api/copy"):
            return httpx.Response(200, text="")
        return httpx.Response(500, text=f"unexpected {method} {url}")


def _install_mock_transport(monkeypatch: pytest.MonkeyPatch,
                            recorder: _Recorder) -> None:
    """Replace ``httpx.AsyncClient`` with a thin wrapper that routes every
    request through ``MockTransport(recorder)`` so the test holds the
    only network endpoint the action ever talks to."""
    transport = httpx.MockTransport(recorder)
    original = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(pub.httpx, "AsyncClient", _factory)


def _pin_data_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MODELFORGE_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "modelforge_data_root", str(tmp_path),
                        raising=False)


def _ctx(track_id: str = "trading-reflector", run_id: str = "run-abc",
         generation: int = 3) -> dict:
    return {
        "track_id": track_id,
        "run_id": run_id,
        "generation": generation,
        "last": {}, "workflow": {"id": "wf-1", "name": "test"},
    }


# ── happy path ─────────────────────────────────────────────────────────


async def test_publish_happy_path_uploads_blob_creates_model_swings_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end happy path:

    * GET /api/tags reachability ping fires
    * PUT /api/blobs/sha256:<hex> carries the .gguf bytes
    * POST /api/create has the right Modelfile fields
    * DELETE /api/delete + POST /api/copy swing the -current alias
    * Returned output has the new versioned name + alias
    """
    _pin_data_root(monkeypatch, tmp_path)
    adir = _seed_adapter(tmp_path, "run-abc", 3,
                         gguf_bytes=b"\x47\x47\x55\x46HELLO")
    recorder = _Recorder()
    _install_mock_transport(monkeypatch, recorder)
    monkeypatch.setattr(settings, "ollama_host",
                        "http://host.docker.internal:11434", raising=False)

    action = PublishAdapterToOllama()
    result = await action.execute(
        config={"base_model": "qwen3:30b"},
        context=_ctx(),
        engine=None,
    )

    assert result.status == "ok", result.message
    assert result.output["model_name"].startswith("qwen3-30b-reflector-v")
    assert result.output["alias"] == "qwen3-30b-reflector-current"
    assert result.output["role"] == "reflector"
    assert result.output["adapter_dir"] == str(adir)
    assert result.output["gguf_path"].endswith("adapter.gguf")
    # Verify the digest carried in the URL matches the file bytes.
    import hashlib
    expected_digest = hashlib.sha256(b"\x47\x47\x55\x46HELLO").hexdigest()
    assert result.output["digest"] == expected_digest

    # Exact request sequence: ping → put blob → create → delete → copy.
    methods = [(r.method, r.url.path) for r in recorder.requests]
    assert methods == [
        ("GET", "/api/tags"),
        ("PUT", f"/api/blobs/sha256:{expected_digest}"),
        ("POST", "/api/create"),
        ("DELETE", "/api/delete"),
        ("POST", "/api/copy"),
    ], methods

    create_body = json.loads(recorder.requests[2].content)
    assert create_body["model"].startswith("qwen3-30b-reflector-v")
    assert create_body["from"] == "qwen3:30b"
    assert create_body["adapters"] == {
        "adapter.gguf": f"sha256:{expected_digest}",
    }
    assert create_body.get("stream") is False

    copy_body = json.loads(recorder.requests[4].content)
    assert copy_body["source"].startswith("qwen3-30b-reflector-v")
    assert copy_body["destination"] == "qwen3-30b-reflector-current"


# ── system prompt is honored ───────────────────────────────────────────


async def test_publish_includes_system_prompt_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_data_root(monkeypatch, tmp_path)
    _seed_adapter(tmp_path, "run-sys", 1)
    recorder = _Recorder()
    _install_mock_transport(monkeypatch, recorder)
    monkeypatch.setattr(settings, "ollama_host", "http://ollama:11434",
                        raising=False)

    result = await PublishAdapterToOllama().execute(
        config={
            "base_model": "qwen3:30b",
            "system_prompt": "You are a trading reflector.",
        },
        context=_ctx(run_id="run-sys", generation=1),
        engine=None,
    )
    assert result.status == "ok"
    create_body = json.loads([r for r in recorder.requests
                              if r.url.path.endswith("/api/create")][0].content)
    assert create_body["system"] == "You are a trading reflector."


# ── Ollama unreachable -> skipped ──────────────────────────────────────


async def test_publish_returns_skipped_when_ollama_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connection refused must produce ``skipped`` (not ``error``) so
    the workflow row doesn't go red just because the host Ollama is
    down for maintenance."""
    _pin_data_root(monkeypatch, tmp_path)
    _seed_adapter(tmp_path, "run-down", 2)

    class _DownRecorder(_Recorder):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            raise httpx.ConnectError("Connection refused", request=request)

    recorder = _DownRecorder()
    _install_mock_transport(monkeypatch, recorder)
    monkeypatch.setattr(settings, "ollama_host", "http://host.docker.internal:11434",
                        raising=False)

    result = await PublishAdapterToOllama().execute(
        config={"base_model": "qwen3:30b"},
        context=_ctx(run_id="run-down", generation=2),
        engine=None,
    )
    assert result.status == "skipped", result.message
    assert "unreachable" in result.message.lower()
    # We pinged once and bailed before any blob upload.
    assert [r.method for r in recorder.requests] == ["GET"]
    assert "intended_model_name" in result.output


# ── adapter dir missing -> error ───────────────────────────────────────


async def test_publish_errors_when_adapter_dir_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_data_root(monkeypatch, tmp_path)
    result = await PublishAdapterToOllama().execute(
        config={"base_model": "qwen3:30b"},
        context=_ctx(run_id="run-nope", generation=99),
        engine=None,
    )
    assert result.status == "error"
    assert result.error == "adapter_dir_missing"


# ── no GGUF + no converter -> skipped ──────────────────────────────────


async def test_publish_skipped_when_no_gguf_and_no_converter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the adapter dir exists, has PEFT safetensors but no .gguf,
    AND no llama.cpp convert_lora_to_gguf.py is available, the action
    must return ``skipped`` with an operator-actionable message rather
    than failing the workflow."""
    _pin_data_root(monkeypatch, tmp_path)
    _seed_adapter(tmp_path, "run-noggm", 4, write_gguf=False)
    monkeypatch.delenv("MODELFORGE_LLAMA_CPP_CONVERT", raising=False)
    monkeypatch.delenv("MODELFORGE_LLAMA_CPP_DIR", raising=False)
    # Force the fixed-path probes to miss.
    monkeypatch.setattr(pub, "_resolve_convert_script", lambda: None)

    result = await PublishAdapterToOllama().execute(
        config={"base_model": "qwen3:30b"},
        context=_ctx(run_id="run-noggm", generation=4),
        engine=None,
    )
    assert result.status == "skipped"
    assert "convert_lora_to_gguf" in result.message
    assert "MODELFORGE_LLAMA_CPP" in result.message


# ── conversion attempted + failed -> error ─────────────────────────────


async def test_publish_errors_when_conversion_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the converter is present but produces non-zero exit, the
    action returns ``error`` -- distinct from the no-converter case."""
    _pin_data_root(monkeypatch, tmp_path)
    _seed_adapter(tmp_path, "run-conv", 5, write_gguf=False)
    monkeypatch.setattr(pub, "_resolve_convert_script", lambda: Path("/fake/convert.py"))

    async def _bad_invoke(script, adapter_dir, out_path, quantization):
        return 2, b"", b"boom: bad tensor shapes"

    monkeypatch.setattr(pub, "_invoke_converter", _bad_invoke)

    result = await PublishAdapterToOllama().execute(
        config={"base_model": "qwen3:30b"},
        context=_ctx(run_id="run-conv", generation=5),
        engine=None,
    )
    assert result.status == "error"
    assert result.error == "gguf_conversion_failed"
    assert "exited 2" in result.message


# ── Ollama create rejects the request -> error ─────────────────────────


async def test_publish_errors_when_create_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_data_root(monkeypatch, tmp_path)
    _seed_adapter(tmp_path, "run-rej", 6)

    class _BadCreate(_Recorder):
        def _respond(self, request):
            if request.method == "GET" and request.url.path.endswith("/api/tags"):
                return httpx.Response(200, json={"models": []})
            if request.method == "PUT" and "/api/blobs/sha256:" in str(request.url):
                return httpx.Response(201)
            if request.url.path.endswith("/api/create"):
                return httpx.Response(400, text="bad modelfile: no FROM")
            return httpx.Response(500)

    recorder = _BadCreate()
    _install_mock_transport(monkeypatch, recorder)
    monkeypatch.setattr(settings, "ollama_host", "http://h:11434", raising=False)

    result = await PublishAdapterToOllama().execute(
        config={"base_model": "qwen3:30b"},
        context=_ctx(run_id="run-rej", generation=6),
        engine=None,
    )
    assert result.status == "error"
    assert result.error == "ollama_create_failed"
    assert "HTTP 400" in result.message
    # We tried delete+copy zero times after create failed.
    methods = [(r.method, r.url.path) for r in recorder.requests]
    assert ("DELETE", "/api/delete") not in methods
    assert ("POST", "/api/copy") not in methods


# ── alias swing fails -> error w/ versioned name preserved ─────────────


async def test_publish_errors_when_alias_swing_fails_but_keeps_model_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_data_root(monkeypatch, tmp_path)
    _seed_adapter(tmp_path, "run-alias", 7)

    class _AliasFails(_Recorder):
        def _respond(self, request):
            if request.method == "GET" and request.url.path.endswith("/api/tags"):
                return httpx.Response(200, json={"models": []})
            if request.method == "PUT" and "/api/blobs/sha256:" in str(request.url):
                return httpx.Response(201)
            if request.url.path.endswith("/api/create"):
                return httpx.Response(200, json={"status": "success"})
            if request.url.path.endswith("/api/delete"):
                return httpx.Response(404, text="not found")
            if request.url.path.endswith("/api/copy"):
                return httpx.Response(409, text="destination already exists and is in use")
            return httpx.Response(500)

    recorder = _AliasFails()
    _install_mock_transport(monkeypatch, recorder)
    monkeypatch.setattr(settings, "ollama_host", "http://h:11434", raising=False)

    result = await PublishAdapterToOllama().execute(
        config={"base_model": "qwen3:30b"},
        context=_ctx(run_id="run-alias", generation=7),
        engine=None,
    )
    assert result.status == "error"
    assert result.error == "alias_failed"
    # The versioned model name is preserved so the operator can re-alias.
    assert result.output["model_name"].startswith("qwen3-30b-reflector-v")
    assert result.output["alias"] == "qwen3-30b-reflector-current"


# ── payload incomplete -> error ────────────────────────────────────────


async def test_publish_errors_on_missing_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_data_root(monkeypatch, tmp_path)
    result = await PublishAdapterToOllama().execute(
        config={"base_model": "qwen3:30b"},
        context={"track_id": "trading-reflector", "last": {}},  # no run_id / generation
        engine=None,
    )
    assert result.status == "error"
    assert "track_id" in result.message
    assert "run_id" in result.message


# ── seed integration ───────────────────────────────────────────────────


def test_seed_workflow_is_registered_and_enabled() -> None:
    """Sanity-check that the new seed lands in DEFAULT_WORKFLOWS with
    the right trigger pattern and enabled=True. Without it the
    track.promoted → ollama bridge can never light up."""
    from services.automation_engine.seeds import DEFAULT_WORKFLOWS
    by_name = {w["name"]: w for w in DEFAULT_WORKFLOWS}
    wf = by_name.get("Publish Promoted Adapter to Ollama")
    assert wf is not None, list(by_name.keys())
    assert wf["enabled"] is True
    assert wf["trigger_type"] == "event"
    assert wf["trigger_config"]["pattern"] == "track.promoted"
    cond = wf["condition"]
    assert cond == {"startswith": [{"var": "track_id"}, "trading-"]}
    kinds = [a["kind"] for a in wf["actions"]]
    assert kinds == ["adapter.publish_ollama", "notify.slack"]


def test_action_registered_in_registry() -> None:
    """The new action must show up in the global registry so workflow
    runners can dispatch to it by kind."""
    from services.automation_engine.actions import ACTION_REGISTRY
    assert "adapter.publish_ollama" in ACTION_REGISTRY
    assert ACTION_REGISTRY["adapter.publish_ollama"] is PublishAdapterToOllama


def test_startswith_condition_operator() -> None:
    """The seed uses ``startswith`` -- which only landed in this PR."""
    from services.automation_engine.conditions import evaluate
    assert evaluate(
        {"startswith": [{"var": "track_id"}, "trading-"]},
        {"track_id": "trading-reflector"},
    ) is True
    assert evaluate(
        {"startswith": [{"var": "track_id"}, "trading-"]},
        {"track_id": "other-track"},
    ) is False


# ── role-name extraction ──────────────────────────────────────────────


def test_role_from_track_id_strips_trading_prefix() -> None:
    from agents.actions.publish_adapter_to_ollama import _role_from_track_id
    assert _role_from_track_id("trading-reflector") == "reflector"
    assert _role_from_track_id("trading-arbiter") == "arbiter"
    assert _role_from_track_id("custom-track") == "custom-track"
    assert _role_from_track_id("") == "unknown"


def test_render_name_substitutes_all_placeholders() -> None:
    name = PublishAdapterToOllama._render_name(
        "{base_model}-{role}-v{date}-g{generation}-{run_id}",
        base_model="qwen3:30b", role="reflector",
        date="20260512", generation=4, run_id="run-x",
    )
    assert name == "qwen3-30b-reflector-v20260512-g4-run-x"


# ── streaming hashing + upload ─────────────────────────────────────────


def test_hash_gguf_streaming_matches_full_read(tmp_path: Path) -> None:
    """The streaming hasher must produce the same digest as a single
    ``read_bytes()`` would, regardless of chunk boundaries.

    We pick a payload bigger than the 8 MiB chunk size so multiple
    iterations fire, and a few "ragged" sizes to make sure the last
    short chunk is handled.
    """
    import hashlib
    import os
    import random

    for size in (1, 4096, 8 * 1024 * 1024, 8 * 1024 * 1024 + 17, 21_000_000):
        rng = random.Random(size)
        payload = bytes(rng.getrandbits(8) for _ in range(size))
        p = tmp_path / f"blob-{size}.gguf"
        p.write_bytes(payload)

        expected = hashlib.sha256(payload).hexdigest()
        digest, reported_size = pub._hash_gguf_streaming(p)
        assert digest == expected, f"size={size}"
        assert reported_size == size

        os.unlink(p)


async def test_publish_streams_blob_via_async_iterator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The PUT request body must be a single contiguous blob equal to
    the file bytes — proves the streaming path arrives intact.

    Why this exists: the previous code did
    ``gguf_bytes = gguf_path.read_bytes()`` and ``client.put(..., content=gguf_bytes)``
    which spikes memory on multi-GB blobs. The streaming rewrite uses an
    async generator; this test pins that arrival is still byte-identical.
    """
    _pin_data_root(monkeypatch, tmp_path)
    payload = b"\x47\x47\x55\x46" + bytes(range(256)) * 1024  # ~256 KB
    _seed_adapter(tmp_path, "run-stream", 1, gguf_bytes=payload)
    recorder = _Recorder()
    _install_mock_transport(monkeypatch, recorder)
    monkeypatch.setattr(settings, "ollama_host",
                        "http://host.docker.internal:11434", raising=False)

    result = await PublishAdapterToOllama().execute(
        config={"base_model": "qwen3:30b"},
        context=_ctx(run_id="run-stream", generation=1),
        engine=None,
    )
    assert result.status == "ok", result.message
    put_request = next(
        r for r in recorder.requests if r.method == "PUT" and "/blobs/" in str(r.url)
    )
    # MockTransport materializes the streamed body into request.content.
    assert put_request.content == payload
    assert put_request.headers.get("content-length") == str(len(payload))
    # Output reports the size we hashed, not 0.
    assert result.output["gguf_size_bytes"] == len(payload)
