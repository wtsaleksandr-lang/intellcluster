from __future__ import annotations

from main_data import app

PATH = "/api/intelligence/company/{slug}/enrich/us-public"


def run() -> int:
    matches = []
    for route in app.router.routes:
        path = str(getattr(route, "path", ""))
        methods = set(getattr(route, "methods", set()) or set())
        if path == PATH and "POST" in methods:
            endpoint = getattr(route, "endpoint", None)
            matches.append(str(getattr(endpoint, "__module__", "")))

    assert matches == ["intelligence.api"], matches
    print("Route hardening checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
