from __future__ import annotations

from main_data import app


def run() -> int:
    superseded = {
        "/api/intelligence/company/{slug}/enrich/us-public",
        "/data/company/{slug}",
        "/data/company/{slug}/bol/{bol_number}",
        "/data/search",
    }
    legacy = []
    relevant = []
    for route in app.router.routes:
        endpoint = getattr(route, "endpoint", None)
        module = str(getattr(endpoint, "__module__", ""))
        endpoint_name = str(getattr(endpoint, "__name__", ""))
        path = str(getattr(route, "path", ""))
        methods = sorted(set(getattr(route, "methods", set()) or set()))
        if "/data/company" in path or path == "/data/search" or "enrich/us-public" in path:
            relevant.append((path, methods, module, endpoint_name))
        if module == "intelligence.ui" and path in superseded:
            legacy.append(path)

    print("Relevant mounted routes:")
    for item in relevant:
        print(item)

    assert not legacy, legacy
    print("Route hardening checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())