#!/usr/bin/env python3
"""Import or update bundled workflows in n8n (REST, idempotent).

**Preferred for Docker dev:** use ``scripts/n8n-import-workflows-compose.sh`` from
``n8n-wait-and-login.sh`` (n8n CLI + bind-mounted JSON — no owner session).

This script is for **HTTP sync** when you have either:

- ``N8N_API_KEY`` — public API ``/api/v1/workflows`` (create n8n API key in the UI), or
- Owner UI credentials — ``N8N_OWNER_EMAIL`` / ``N8N_OWNER_PASSWORD`` plus basic auth,
  using the internal ``/rest/login`` session (n8n ≥ 1.102 expects ``emailOrLdapLoginId``).

Idempotent by workflow **name**: PATCH existing, POST new, then sync ``active``.

Set N8N_SKIP_WORKFLOW_IMPORT=1 to no-op.

Usage::

    export N8N_URL=http://localhost:5679
    export N8N_API_KEY=n8n_api_...
    python3 scripts/n8n_import_workflows.py
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "integrations" / "n8n" / "workflows"

BASE = os.environ.get("N8N_URL", "http://localhost:5678").rstrip("/")
API_KEY = os.environ.get("N8N_API_KEY", "").strip()
BASIC_USER = os.environ.get("N8N_BASIC_AUTH_USER", "admin")
BASIC_PASS = os.environ.get("N8N_BASIC_AUTH_PASSWORD", "")
OWNER_EMAIL = os.environ.get("N8N_OWNER_EMAIL", "admin@modelforge.local")
OWNER_PASSWORD = os.environ.get("N8N_OWNER_PASSWORD") or BASIC_PASS

_NODE_STRIP = frozenset({"credentials"})


def _client_headers() -> dict[str, str]:
    """Headers for n8n HTTP calls (public API key and/or reverse-proxy basic auth)."""
    h: dict[str, str] = {"Content-Type": "application/json"}
    if API_KEY:
        h["X-N8N-API-KEY"] = API_KEY
    if BASIC_PASS:
        token = base64.b64encode(f"{BASIC_USER}:{BASIC_PASS}".encode()).decode()
        h["Authorization"] = f"Basic {token}"
    return h


def _clean_nodes(nodes: list) -> list:
    out: list = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        cleaned = {k: v for k, v in node.items() if k not in _NODE_STRIP}
        # Let n8n assign DB ids; connections use node **names**.
        cleaned.pop("id", None)
        out.append(cleaned)
    return out


def clean_workflow_payload(raw: dict) -> dict:
    """Shape acceptable for POST/PATCH /rest/workflows."""
    payload: dict = {
        "name": raw.get("name") or "Imported workflow",
        "nodes": _clean_nodes(list(raw.get("nodes") or [])),
        "connections": raw.get("connections") or {},
        "settings": raw.get("settings") or {},
    }
    if raw.get("staticData") is not None:
        payload["staticData"] = raw["staticData"]
    return payload


def _parse_workflow_list(data: object) -> list[dict]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []
    inner = data.get("data")
    if isinstance(inner, list):
        return [x for x in inner if isinstance(x, dict)]
    if isinstance(inner, dict):
        for key in ("workflows", "result", "Workflows"):
            v = inner.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    for key in ("workflows", "Workflows"):
        v = data.get(key)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
    return []


def _login(client: httpx.Client) -> None:
    if not OWNER_PASSWORD:
        print("N8N_OWNER_PASSWORD (or basic auth password) required for REST session import.", file=sys.stderr)
        sys.exit(1)
    # Current n8n expects emailOrLdapLoginId; keep legacy "email" as fallback.
    attempts = (
        {"emailOrLdapLoginId": OWNER_EMAIL, "password": OWNER_PASSWORD},
        {"email": OWNER_EMAIL, "password": OWNER_PASSWORD},
    )
    last_err = ""
    for body in attempts:
        r = client.post(f"{BASE}/rest/login", json=body)
        if r.status_code in (200, 201):
            return
        last_err = f"{r.status_code}: {r.text[:300]}"
    print(f"n8n login failed at {BASE}/rest/login — {last_err}", file=sys.stderr)
    sys.exit(4)


def _list_workflows(client: httpx.Client) -> dict[str, str]:
    if API_KEY:
        r = client.get(f"{BASE}/api/v1/workflows")
    else:
        r = client.get(f"{BASE}/rest/workflows")
    if r.status_code != 200:
        print(f"List workflows → {r.status_code}: {r.text[:400]}", file=sys.stderr)
        sys.exit(5)
    data = r.json()
    if API_KEY and isinstance(data, dict) and "data" in data:
        items = data["data"]
    else:
        items = _parse_workflow_list(data)
    by_name: dict[str, str] = {}
    for wf in items:
        if not isinstance(wf, dict):
            continue
        wid = wf.get("id")
        name = wf.get("name")
        if isinstance(name, str) and wid is not None:
            by_name[name] = str(wid)
    return by_name


def _set_active(client: httpx.Client, workflow_id: str, active: bool) -> None:
    if API_KEY:
        url = f"{BASE}/api/v1/workflows/{workflow_id}"
        r = client.patch(url, json={"active": active})
    else:
        r = client.patch(
            f"{BASE}/rest/workflows/{workflow_id}",
            json={"active": active},
        )
    if r.status_code not in (200, 201):
        print(
            f"PATCH active={active} for {workflow_id} → {r.status_code}: {r.text[:300]}",
            file=sys.stderr,
        )


def import_all(workflows_dir: Path, files: list[Path]) -> None:
    if os.environ.get("N8N_SKIP_WORKFLOW_IMPORT", "").strip().lower() in ("1", "true", "yes"):
        print("N8N_SKIP_WORKFLOW_IMPORT set — skipping workflow import.")
        return

    if not API_KEY and not BASIC_PASS:
        print("Set N8N_API_KEY and/or N8N_BASIC_AUTH_PASSWORD for REST import.", file=sys.stderr)
        sys.exit(1)

    headers = _client_headers()
    with httpx.Client(timeout=120.0, follow_redirects=True, headers=headers) as client:
        h = client.get(f"{BASE}/healthz")
        h.raise_for_status()

        if not API_KEY:
            _login(client)
        existing = _list_workflows(client)

        for path in files:
            raw = json.loads(path.read_text(encoding="utf-8"))
            name = raw.get("name") or path.stem
            body = clean_workflow_payload(raw)
            want_active = bool(raw.get("active"))

            wf_id = existing.get(name)
            if wf_id:
                body["id"] = wf_id
                if API_KEY:
                    r = client.patch(f"{BASE}/api/v1/workflows/{wf_id}", json=body)
                else:
                    r = client.patch(f"{BASE}/rest/workflows/{wf_id}", json=body)
                action = "updated"
            else:
                if API_KEY:
                    r = client.post(f"{BASE}/api/v1/workflows", json=body)
                else:
                    r = client.post(f"{BASE}/rest/workflows", json=body)
                action = "created"
            if r.status_code not in (200, 201):
                print(
                    f"{path.name} ({name}) → {r.status_code}: {r.text[:500]}",
                    file=sys.stderr,
                )
                sys.exit(6)
            data = r.json()
            new_id = data.get("id") if isinstance(data, dict) else None
            if isinstance(new_id, str):
                existing[name] = new_id
                wf_id = new_id

            if wf_id and want_active:
                _set_active(client, wf_id, True)
            elif wf_id and not want_active:
                _set_active(client, wf_id, False)

            print(f"  {action}: {name} ({path.name})")


def main() -> None:
    wf_dir = Path(os.environ.get("N8N_WORKFLOWS_DIR", str(DEFAULT_DIR))).resolve()
    if not wf_dir.is_dir():
        print(f"Workflows directory missing: {wf_dir}", file=sys.stderr)
        sys.exit(1)
    files = sorted(wf_dir.glob("*.json"))
    if not files:
        print(f"No workflow JSON files in {wf_dir}", file=sys.stderr)
        sys.exit(1)
    print(f"Importing workflows from {wf_dir} → {BASE} (REST, API key={'yes' if API_KEY else 'no'})")
    import_all(wf_dir, files)


if __name__ == "__main__":
    main()
