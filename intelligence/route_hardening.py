from __future__ import annotations

from typing import Any

LEGACY_US_PUBLIC_PATH = "/api/intelligence/company/{slug}/enrich/us-public"
LEGACY_COMPANY_PATH = "/data/company/{slug}"
LEGACY_BOL_PATH = "/data/company/{slug}/bol/{bol_number}"
LEGACY_SEARCH_PATH = "/data/search"

_PAGE_REPLACEMENTS = {
    (LEGACY_COMPANY_PATH, "GET"),
    (LEGACY_BOL_PATH, "GET"),
    (LEGACY_SEARCH_PATH, "GET"),
}


def _route_path(route: Any) -> str:
    return str(getattr(route, "path", None) or getattr(route, "path_format", None) or "")


def _prune_routes(routes: list[Any]) -> int:
    """Recursively remove routes that are superseded before focused mounts.

    ``main_data.py`` calls this after importing ``main_data_core`` but before it
    mounts the focused company/search routers. Therefore every pre-existing GET
    registration for those exact page paths is obsolete, regardless of how the
    installed FastAPI version wraps the originating router. This is deliberately
    path/method based instead of relying on ``endpoint.__module__`` metadata.

    The U.S. public enrichment route is different: the canonical implementation
    from ``intelligence.api`` is already mounted by ``main_data_core`` and must be
    preserved. Only competing registrations for that POST are removed.
    """
    kept: list[Any] = []
    removed = 0
    for route in routes:
        children = getattr(route, "routes", None)
        if isinstance(children, list):
            removed += _prune_routes(children)

        endpoint = getattr(route, "endpoint", None)
        module = str(getattr(endpoint, "__module__", ""))
        path = _route_path(route)
        methods = set(getattr(route, "methods", set()) or set())

        replace_page = any(
            path == target and method in methods
            for target, method in _PAGE_REPLACEMENTS
        )
        replace_us_public = (
            path == LEGACY_US_PUBLIC_PATH
            and "POST" in methods
            and module != "intelligence.api"
        )
        if replace_page or replace_us_public:
            removed += 1
            continue
        kept.append(route)

    routes[:] = kept
    return removed


def prune_shadowed_legacy_routes(app: Any) -> int:
    """Remove superseded registrations before focused canonical routes mount."""
    return _prune_routes(app.router.routes)
