#!/usr/bin/env python3
"""ModelForge live smoke test against http://localhost:8000.

Pass the API key via the MODELFORGE_API_KEY env var (mirrors what the
SPA sends via the X-API-Key header).
"""

from __future__ import annotations

import os
import sys

import httpx

BASE_URL = os.environ.get("MODELFORGE_BASE_URL", "http://localhost:8000")
API_KEY = os.environ.get("MODELFORGE_API_KEY", "")

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"

passed = 0
failed = 0


def check(label: str, result: bool, detail: str = "") -> None:
    global passed, failed
    if result:
        passed += 1
        status = f"{GREEN}PASS{RESET}"
    else:
        failed += 1
        status = f"{RED}FAIL{RESET}"
    suffix = f"  {YELLOW}({detail}){RESET}" if detail else ""
    print(f"  [{status}] {label}{suffix}")


def main() -> None:
    print(f"\n{BOLD}ModelForge smoke tests — {BASE_URL}{RESET}")
    print("=" * 60)

    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    client = httpx.Client(timeout=10.0, headers=headers)

    # 1. Health
    try:
        r = client.get(f"{BASE_URL}/api/system/health")
        check("Health returns 200", r.status_code == 200, f"got {r.status_code}")
        body = r.json()
    except Exception as exc:
        check("Health returns 200", False, str(exc))
        body = {}

    # 2. Postgres status reported by the API ("ok" or "degraded")
    pg = body.get("postgres", "MISSING")
    check("Health postgres in {ok, degraded}", pg in {"ok", "degraded"}, f"got '{pg}'")

    # 3. GPU
    try:
        r = client.get(f"{BASE_URL}/api/system/gpu")
        check("GPU returns 200", r.status_code == 200, f"got {r.status_code}")
        gpu_body = r.json()
    except Exception as exc:
        check("GPU returns 200", False, str(exc))
        gpu_body = {}

    check(
        "GPU response includes gpu_available",
        "gpu_available" in gpu_body,
        f"keys: {sorted(gpu_body.keys())}",
    )

    # 4. Champion
    try:
        r = client.get(f"{BASE_URL}/api/models/champion")
        check("Champion returns 200", r.status_code == 200, f"got {r.status_code}")
    except Exception as exc:
        check("Champion returns 200", False, str(exc))

    # 5. Lineage
    try:
        r = client.get(f"{BASE_URL}/api/lineage/tree")
        check("Lineage returns 200", r.status_code == 200, f"got {r.status_code}")
        lineage_body = r.json()
    except Exception as exc:
        check("Lineage returns 200", False, str(exc))
        lineage_body = {}

    nodes = lineage_body.get("nodes", [])
    check("Lineage has at least one node", len(nodes) >= 1, f"got {len(nodes)}")

    # 6. Eval scores
    try:
        r = client.get(f"{BASE_URL}/api/eval/scores")
        check("Eval scores returns 200", r.status_code == 200, f"got {r.status_code}")
        scores_body = r.json()
    except Exception as exc:
        check("Eval scores returns 200", False, str(exc))
        scores_body = {}

    trends = scores_body.get("trends", [])
    check("Eval scores has trends array", len(trends) >= 1, f"got {len(trends)}")

    # 7. Benchmarks catalog
    try:
        r = client.get(f"{BASE_URL}/api/eval/benchmarks")
        bench_body = r.json()
        benches = bench_body.get("benchmarks", [])
        check("Benchmarks list has 5 items", len(benches) == 5, f"got {len(benches)}")
    except Exception as exc:
        check("Benchmarks list has 5 items", False, str(exc))

    # 8. Evolve start (with valid body)
    try:
        r = client.post(
            f"{BASE_URL}/api/evolve/start",
            json={"base_model": "llama3.2:3b", "max_generations": 1},
        )
        check("Evolve start returns 200", r.status_code == 200, f"got {r.status_code}")
        evolve_body = r.json()
        check(
            "Evolve start includes run_id",
            isinstance(evolve_body.get("run_id"), str)
            and evolve_body["run_id"].startswith("run-"),
            f"body: {evolve_body}",
        )
    except Exception as exc:
        check("Evolve start returns 200", False, str(exc))

    client.close()

    total = passed + failed
    print("=" * 60)
    if failed == 0:
        print(f"{BOLD}{GREEN}ALL TESTS PASSED{RESET}  ({passed}/{total} passed)\n")
    else:
        print(
            f"{BOLD}{RED}{failed} TEST(S) FAILED{RESET}  ({passed}/{total} passed)\n"
        )

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
