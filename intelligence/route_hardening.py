from __future__ import annotations

from typing import Any

LEGACY_US_PUBLIC_PATH = "/api/intelligence/company/{slug}/enrich/us-public"


def prune_shadowed_legacy_routes(app: Any) -> int:
    """Remove the obsolete UI-layer copy of the U.S. enrichment POST route.

    ``main_data_core`` historically mounted both ``intelligence.api`` and
    ``intelligence.ui`` implementations for the same path. The API implementation
    is the canonical free-only endpoint and is mounted first, so the UI copy was
    unreachable but remained technical debt. Pruning it after core app import
    keeps runtime routing unambiguous without rewriting the large legacy UI module.
    """
    kept = []
    removed = 0
    for route in app.router.routes:
        endpoint = getattr(route, "endpoint", None)
        module = str(getattr(endpoint, "__module__", ""))
        path = str(getattr(route, "path", ""))
        methods = set(getattr(route, "methods", set()) or set())
        if path == LEGACY_US_PUBLIC_PATH and "POST" in methods and module == "intelligence.ui":
            removed += 1
            continue
        kept.append(route)
    if removed:
        app.router.routes[:] = kept
    return removed
