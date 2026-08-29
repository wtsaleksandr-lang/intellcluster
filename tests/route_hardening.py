from __future__ import annotations

from main_data import app


def _owners(path: str, method: str) -> list[str]:
    owners = []
    for route in app.router.routes:
        if str(getattr(route, "path", "")) != path:
            continue
        methods = set(getattr(route, "methods", set()) or set())
        if method not in methods:
            continue
        endpoint = getattr(route, "endpoint", None)
        owners.append(str(getattr(endpoint, "__module__", "")))
    return owners


def run() -> int:
    assert _owners(
        "/api/intelligence/company/{slug}/enrich/us-public", "POST"
    ) == ["intelligence.api"]
    assert _owners("/data/company/{slug}", "GET") == ["intelligence.company_routes"]
    assert _owners("/data/company/{slug}/bol/{bol_number}", "GET") == [
        "intelligence.company_routes"
    ]

    for route in app.router.routes:
        endpoint = getattr(route, "endpoint", None)
        module = str(getattr(endpoint, "__module__", ""))
        path = str(getattr(route, "path", ""))
        if module == "intelligence.ui" and path in {
            "/api/intelligence/company/{slug}/enrich/us-public",
            "/data/company/{slug}",
            "/data/company/{slug}/bol/{bol_number}",
        }:
            raise AssertionError(f"Legacy UI route still mounted: {path}")

    print("Route hardening checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())