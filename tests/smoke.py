"""
Smoke test — asserts every public route responds with a non-error status.

Runs the FastAPI app in-process via starlette TestClient (no network, no
uvicorn needed). Safe to run in CI with zero API keys — no LLM calls are
executed because we hit GET routes + one POST that doesn't reach the model.

Usage:
    python -m tests.smoke
    # or pytest -q tests/smoke.py
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

# Force UTF-8 stdout so arrow glyphs in output don't crash on Windows cp1252.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Make `main` importable from repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Smoke runs must never write real analytics or send real emails
os.environ.setdefault("ADMIN_PASSWORD", "smoke-test-pw")
os.environ.setdefault("ADMIN_USERNAME", "smoke")
os.environ.setdefault("ADMIN_SECRET_KEY", "smoke-secret-key")

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402


client = TestClient(app)


PUBLIC_ROUTES = [
    ("/", 200),
    ("/phronesis", 200),
    ("/synthesis", 200),
    ("/pricing", 200),
    ("/compare", 200),
    ("/templates", 200),
    ("/history", 200),
    ("/privacy", 200),
    ("/terms", 200),
    ("/robots.txt", 200),
    ("/llm.txt", 200),
    ("/sitemap.xml", 200),
    ("/favicon.svg", 200),
    ("/og/homepage.svg", 200),
    ("/api/health", 200),
    ("/pricing/upgrade", 200),
    # A specific compare page (must exist in data/compare_pages.json)
    ("/compare/hubspot-vs-salesforce-vs-pipedrive", 200),
    ("/og/compare/hubspot-vs-salesforce-vs-pipedrive.svg", 200),
    ("/og/compare/hubspot-vs-salesforce-vs-pipedrive.png", 200),
    ("/og/homepage.png", 200),
    ("/templates/choose-laptop", 200),
    ("/og/template/choose-laptop.png", 200),
    # Static pages
    ("/about", 200),
    ("/contact", 200),
    ("/faq", 200),
    ("/docs", 200),
    # Phronesis OS advisory — new in V1.5
    ("/advisory", 200),
    ("/advisory/result/does-not-exist", 404),
    ("/advisory/api/session/does-not-exist", 404),
    # Magic-link auth
    ("/login", 200),
    ("/account", 302),  # redirects to /login when unauthenticated
    ("/auth/verify?token=garbage", 400),
    # Blog foundation — works with zero posts, renders empty state
    ("/blog", 200),
    ("/blog.xml", 200),
    ("/blog/does-not-exist", 404),
    # First live field note — published 2026-04-22
    ("/blog/blind-multi-analyst-scoring", 200),
    ("/og/blog/blind-multi-analyst-scoring.png", 200),
    # Tag page for the live article's tags
    ("/blog/tag/methodology", 200),
    ("/blog/tag/does-not-exist", 404),
    # Scheduled posts remain 404 until their publish_date
    ("/blog/multi-model-research-vs-single-llm", 404),
    # 404 path returns a templated 404 with status 404
    ("/compare/definitely-does-not-exist", 404),
    # Legacy redirects
    ("/decide", 302),
]


ADMIN_GATE_ROUTES = [
    # Admin routes must redirect unauthenticated users to /admin/login
    "/admin",
    "/admin/waitlist",
    "/admin/analytics",
    "/admin/users",
    "/admin/contact",
    "/admin/purchases",
]


def _check(method: str, path: str, expected_status: int, **kwargs) -> tuple[bool, str]:
    resp = client.request(method, path, follow_redirects=False, **kwargs)
    if resp.status_code == expected_status:
        return True, f"ok  {method} {path} -> {resp.status_code}"
    return False, f"FAIL {method} {path} -> {resp.status_code} (expected {expected_status})"


def run() -> int:
    failures: list[str] = []
    results: list[str] = []

    # Public routes
    for path, expected in PUBLIC_ROUTES:
        ok, msg = _check("GET", path, expected)
        results.append(msg)
        if not ok:
            failures.append(msg)

    # Admin gating — unauth => 302 to /admin/login
    for path in ADMIN_GATE_ROUTES:
        resp = client.get(path, follow_redirects=False)
        if resp.status_code == 302 and "/admin/login" in resp.headers.get("location", ""):
            results.append(f"ok  GET {path} (gated → /admin/login)")
        else:
            msg = f"FAIL GET {path} -> {resp.status_code} loc={resp.headers.get('location')} (expected 302 to /admin/login)"
            results.append(msg)
            failures.append(msg)

    # Intent classifier should return a JSON payload (no external key needed; heuristic path)
    resp = client.post("/api/intent", json={"text": "Should I choose HubSpot or Salesforce for our CRM?"})
    if resp.status_code == 200 and "tool" in resp.json():
        results.append("ok  POST /api/intent (returned tool)")
    else:
        msg = f"FAIL POST /api/intent -> {resp.status_code} body={resp.text[:120]}"
        results.append(msg)
        failures.append(msg)

    # Template lookup
    resp = client.get("/api/template/choose-laptop")
    if resp.status_code == 200 and resp.json().get("options"):
        results.append("ok  GET /api/template/choose-laptop")
    else:
        msg = f"FAIL GET /api/template/choose-laptop -> {resp.status_code}"
        results.append(msg)
        failures.append(msg)

    # Compare preset lookup
    resp = client.get("/api/compare-preset/hubspot-vs-salesforce-vs-pipedrive")
    if resp.status_code == 200 and resp.json().get("options"):
        results.append("ok  GET /api/compare-preset/hubspot-vs-salesforce-vs-pipedrive")
    else:
        msg = f"FAIL GET /api/compare-preset/... -> {resp.status_code}"
        results.append(msg)
        failures.append(msg)

    # Admin login flow (valid credentials → 302 to /admin with cookie)
    resp = client.post(
        "/admin/login",
        data={"username": os.environ["ADMIN_USERNAME"], "password": os.environ["ADMIN_PASSWORD"]},
        follow_redirects=False,
    )
    if resp.status_code == 302 and resp.headers.get("location", "").endswith("/admin"):
        results.append("ok  POST /admin/login (valid creds → /admin)")
    else:
        msg = f"FAIL admin login -> {resp.status_code} loc={resp.headers.get('location')}"
        results.append(msg)
        failures.append(msg)

    # Print results
    print("\n".join(results))
    print()
    if failures:
        print(f"SMOKE FAILED: {len(failures)} failure(s)")
        return 1
    print(f"SMOKE OK: {len(results)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(run())
