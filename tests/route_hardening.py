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
    routes = list(app.router.routes)
    print(f"App type={type(app)!r} router={type(app.router)!r} route_count={len(routes)}")
    for index, route in enumerate(routes[:30]):
        print(
            "ROUTE",
            index,
            type(route).__name__,
            repr(getattr(route, "path", None)),
            repr(getattr(route, "path_format", None)),
            repr(sorted(set(getattr(route, "methods", set()) or set()))),
            repr(getattr(getattr(route, "endpoint", None), "__module__", None)),
            repr(getattr(getattr(route, "endpoint", None), "__name__", None)),
        )
    for route in routes:
        endpoint = getattr(route, "endpoint", None)
        module = str(getattr(endpoint, "__module__", ""))
        endpoint_name = str(getattr(endpoint, "__name__", ""))
        path = str(getattr(route, "path", ""))
        path_format = str(getattr(route, "path_format", ""))
        methods = sorted(set(getattr(route, "methods", set()) or set()))
        probe = path or path_format
        if "/data/company" in probe or probe == "/data/search" or "enrich/us-public" in probe:
            relevant.append((path, path_format, methods, module, endpoint_name))
        if module == "intelligence.ui" and probe in superseded:
            legacy.append(probe)

    print("Relevant mounted routes:")
    for item in relevant:
        print(item)

    assert not legacy, legacy
    print("Route hardening checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())