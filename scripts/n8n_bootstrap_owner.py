#!/usr/bin/env python3
"""Create the n8n *instance owner* (first-time setup) via the REST API.

Requires Basic Auth (N8N_BASIC_AUTH_* from docker-compose) because the
editor is protected. Safe to run multiple times — exits 0 if an owner
already exists.

Usage (from repo root, stack running)::

    export N8N_URL=http://localhost:5679
    export N8N_BASIC_AUTH_USER=admin
    export N8N_BASIC_AUTH_PASSWORD=your-basic-auth-password
    export N8N_OWNER_EMAIL=admin@modelforge.local
    export N8N_OWNER_PASSWORD=your-owner-password
    python3 scripts/n8n_bootstrap_owner.py
"""

from __future__ import annotations

import base64
import os
import sys

import httpx

BASE = os.environ.get("N8N_URL", "http://localhost:5679").rstrip("/")
BASIC_USER = os.environ.get("N8N_BASIC_AUTH_USER", "admin")
BASIC_PASS = os.environ.get("N8N_BASIC_AUTH_PASSWORD", "")
OWNER_EMAIL = os.environ.get("N8N_OWNER_EMAIL", "admin@modelforge.local")
OWNER_PASSWORD = os.environ.get("N8N_OWNER_PASSWORD") or BASIC_PASS
FIRST = os.environ.get("N8N_OWNER_FIRST_NAME", "Model")
LAST = os.environ.get("N8N_OWNER_LAST_NAME", "Forge")


def _basic_header() -> dict[str, str]:
    token = base64.b64encode(f"{BASIC_USER}:{BASIC_PASS}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def main() -> None:
    if not BASIC_PASS:
        print("N8N_BASIC_AUTH_PASSWORD is required.", file=sys.stderr)
        sys.exit(1)
    if not OWNER_PASSWORD:
        print("N8N_OWNER_PASSWORD (or BASIC_PASS) is required.", file=sys.stderr)
        sys.exit(1)

    headers = {
        **_basic_header(),
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        try:
            health = client.get(f"{BASE}/healthz")
            health.raise_for_status()
        except Exception as exc:
            print(f"n8n not reachable at {BASE}/healthz: {exc}", file=sys.stderr)
            sys.exit(2)

        # Probe whether user management / owner already exists.
        try:
            r = client.get(f"{BASE}/rest/settings", headers=_basic_header())
            if r.status_code == 200:
                data = r.json()
                if data.get("userManagement", {}).get("showSetupOnFirstLoad") is False:
                    print("n8n owner already configured — nothing to do.")
                    return
        except Exception:
            pass

        # n8n ≥ 1.30 first-launch endpoint (name may vary by minor version).
        for path in ("/rest/owner/setup", "/rest/owner"):
            try:
                resp = client.post(
                    f"{BASE}{path}",
                    headers=headers,
                    json={
                        "email": OWNER_EMAIL,
                        "password": OWNER_PASSWORD,
                        "firstName": FIRST,
                        "lastName": LAST,
                    },
                )
                if resp.status_code in (200, 201):
                    print(f"Owner created via POST {path} — log in at {BASE} as {OWNER_EMAIL}")
                    return
                if resp.status_code == 400 and "already" in resp.text.lower():
                    print("Owner already exists.")
                    return
                print(f"{path} → {resp.status_code}: {resp.text[:500]}", file=sys.stderr)
            except Exception as exc:
                print(f"{path} failed: {exc}", file=sys.stderr)

        print(
            "Automatic owner creation failed — open the UI once and complete signup manually.",
            file=sys.stderr,
        )
        sys.exit(3)


if __name__ == "__main__":
    main()
