from __future__ import annotations

from typing import Any

from intelligence.api import router as intelligence_api_router
from intelligence.company_routes import router as company_router
from intelligence.search_routes import router as search_router
from main_data import app

_SUPERSEDED = {
    "/api/intelligence/company/{slug}/enrich/us-public",
    "/data/company/{slug}",
    "/data/company/{slug}/bol/{bol_number}",
    "/data/search",
}


def _walk(routes: Any):
    for route in routes or []:
        yield route
        children = getattr(route, "routes", None)
        if children is not None:
            yield from _walk(children)


def _path(route: Any) -> str:
    return str(getattr(route, "path", None) or getattr(route, "path_format", None) or "")


def _router_has(router: Any, path: str, method: str, module: str) -> bool:
    for route in _walk(getattr(router, "routes", [])):
        if _path(route) != path:
            continue
        if method not in set(getattr(route, "methods", set()) or set()):
            continue
        endpoint = getattr(route, "endpoint", None)
        if str(getattr(endpoint, "__module__", "")) == module:
            return True
    return False


def run() -> int:
    # Focused routers must own the canonical implementations themselves. This is
    # more stable than assuming FastAPI will always flatten included routers into
    # the application with identical internal route objects.
    assert _router_has(
        company_router,
        "/data/company/{slug}",
        "GET",
        "intelligence.company_routes",
    )
    assert _router_has(
        company_router,
        "/data/company/{slug}/bol/{bol_number}",
        "GET",
        "intelligence.company_routes",
    )
    assert _router_has(
        search_router,
        "/data/search",
        "GET",
        "intelligence.search_routes",
    )
    assert _router_has(
        intelligence_api_router,
        "/api/intelligence/company/{slug}/enrich/us-public",
        "POST",
        "intelligence.api",
    )

    # No superseded route may remain mounted from the legacy monolithic UI
    # router. Focused behavior is covered separately by company/search/API tests.
    legacy = []
    for route in _walk(getattr(app.router, "routes", [])):
        endpoint = getattr(route, "endpoint", None)
        module = str(getattr(endpoint, "__module__", ""))
        path = _path(route)
        if module == "intelligence.ui" and path in _SUPERSEDED:
            legacy.append((path, sorted(set(getattr(route, "methods", set()) or set()))))
    assert not legacy, legacy

    print("Route hardening checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
