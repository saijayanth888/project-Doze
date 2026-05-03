#!/usr/bin/env python3
"""Static checks on bundled n8n workflow JSON (no live n8n / MCP required).

Exit 0 if all checks pass; non-zero otherwise. Intended for CI::

    python3 scripts/validate_n8n_workflow_bundle.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF_DIR = ROOT / "integrations" / "n8n" / "workflows"

# Block accidental commit of obvious secrets in node parameters (values only).
BAD_VALUE_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{20,}", re.I),
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}", re.I),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]+", re.I),
)


def _walk_strings(obj: object, path: str = "") -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else k
            hits.extend(_walk_strings(v, p))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits.extend(_walk_strings(v, f"{path}[{i}]"))
    elif isinstance(obj, str):
        if path:
            hits.append((path, obj))
    return hits


def _check_file(path: Path) -> list[str]:
    errs: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{path.name}: invalid JSON ({exc})"]
    if not isinstance(data, dict):
        return [f"{path.name}: root must be object"]
    for key in ("name", "nodes", "connections"):
        if key not in data:
            errs.append(f"{path.name}: missing top-level {key!r}")
    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        errs.append(f"{path.name}: nodes must be non-empty array")
    else:
        for i, node in enumerate(nodes):
            if not isinstance(node, dict):
                errs.append(f"{path.name}: nodes[{i}] must be object")
                continue
            if "type" not in node or "name" not in node:
                errs.append(f"{path.name}: nodes[{i}] missing type or name")
    for loc, s in _walk_strings(data.get("nodes")):
        for pat in BAD_VALUE_PATTERNS:
            if pat.search(s):
                errs.append(f"{path.name}: suspicious token in {loc}")
                break
    return errs


def main() -> int:
    if not WF_DIR.is_dir():
        print(f"Missing {WF_DIR}", file=sys.stderr)
        return 1
    files = sorted(WF_DIR.glob("*.json"))
    if not files:
        print(f"No JSON in {WF_DIR}", file=sys.stderr)
        return 1
    all_errs: list[str] = []
    for path in files:
        all_errs.extend(_check_file(path))
    if all_errs:
        print("\n".join(all_errs), file=sys.stderr)
        return 2
    print(f"OK: {len(files)} workflow file(s) in {WF_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
