from __future__ import annotations

from typing import Any

LEGACY_US_PUBLIC_PATH = "/api/intelligence/company/{slug}/enrich/us-public"
LEGACY_COMPANY_PATH = "/data/company/{slug}"
LEGACY_BOL_PATH = "/data/company/{slug}/bol/{bol_number}"
LEGACY_SEARCH_PATH = "/data/search"

_SUPERSEDED = {
    (LEGACY_US_PUBLIC_PATH, "POST"),
    (LEGACY_COMPANY_PATH, "GET"),
    (LEGACY_BOL_PATH, "GET"),
    (LEGACY_SEARCH_PATH, "GET"),
}


def _prune_routes(routes: list[Any]) -> int:
    """Recursively remove superseded routes owned by ``intelligence.ui``.

    FastAPI 0.141 keeps included routers as nested ``_IncludedRouter`` objects,
    while older versions flatten them. Walking ``.routes`` recursively works with
    both representations and avoids relying on framework-version-specific layout.
    """
    kept: list[Any] = []
    removed = 0
    for route in routes:
        children = getattr(route, "routes", None)
        if isinstance(children, list):
            removed += _prune_routes(children)

        endpoint = getattr(route, "endpoint", None)
        module = str(getattr(endpoint, "__module__", ""))
        path = str(getattr(route, "path", ""))
        methods = set(getattr(route, "methods", set()) or set())
        is_superseded = any(path == target and method in methods for target, method in _SUPERSEDED)
        if module == "intelligence.ui" and is_superseded:
            removed += 1
            continue
        kept.append(route)

    if removed:
        routes[:] = kept
    return removed


def prune_shadowed_legacy_routes(app: Any) -> int:
    """Remove only legacy UI routes replaced by focused canonical modules.

    ``main_data_core`` still mounts ``intelligence.ui`` for older pages that have
    not yet been migrated. Company profiles, cached BOL detail, truthful search and
    the U.S. public-enrichment action have focused implementations, so their old UI
    registrations are removed before those focused page routers are mounted.
    """
    return _prune_routes(app.router.routes)
