from __future__ import annotations

from typing import Any

from main_data import app

_SUPERSEDED = {
    "/api/intelligence/company/{slug}/enrich/us-public",
    "/data/company/{slug}",
    "/data/company/{slug}/bol/{bol_number}",
    "/data/search",
}


def _walk(routes: list[Any]):
    for route in routes:
        yield route
        children = getattr(route, "routes", None)
        if isinstance(children, list):
            yield from _walk(children)


def run() -> int:
    relevant = []
    legacy = []
    for route in _walk(list(app.router.routes)):
        endpoint = getattr(route, "endpoint", None)
        module = str(getattr(endpoint, "__module__", ""))
        endpoint_name = str(getattr(endpoint, "__name__", ""))
        path = str(getattr(route, "path", ""))
        methods = sorted(set(getattr(route, "methods", set()) or set()))
        if path in _SUPERSEDED:
            relevant.append((path, methods, module, endpoint_name))
            if module == "intelligence.ui":
                legacy.append((path, methods, endpoint_name))

    assert not legacy, legacy
    assert (
        "/data/company/{slug}",
        ["GET"],
        "intelligence.company_routes",
        "intelligence_company_page",
    ) in relevant, relevant
    assert (
        "/data/company/{slug}/bol/{bol_number}",
        ["GET"],
        "intelligence.company_routes",
        "intelligence_cached_bol_page",
    ) in relevant, relevant
    assert (
        "/data/search",
        ["GET"],
        "intelligence.search_routes",
        "intelligence_search_page",
    ) in relevant, relevant
    assert sum(
        1
        for path, methods, module, _name in relevant
        if path == "/api/intelligence/company/{slug}/enrich/us-public"
        and "POST" in methods
        and module == "intelligence.api"
    ) == 1, relevant

    print("Route hardening checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())