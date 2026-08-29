from __future__ import annotations

from typing import Any

LEGACY_US_PUBLIC_PATH = "/api/intelligence/company/{slug}/enrich/us-public"
LEGACY_COMPANY_PATH = "/data/company/{slug}"
LEGACY_BOL_PATH = "/data/company/{slug}/bol/{bol_number}"


def prune_shadowed_legacy_routes(app: Any) -> int:
    """Remove legacy UI routes superseded by focused canonical implementations.

    ``main_data_core`` still mounts ``intelligence.ui`` because it contains several
    historical directory pages. Newer focused modules own company profiles, cached
    BOL detail and the free-only U.S. enrichment action. Pruning only the exact
    superseded routes keeps the remaining legacy UI pages working while preventing
    duplicate registrations and accidental execution of old live-enrichment code.
    """
    kept = []
    removed = 0
    for route in app.router.routes:
        endpoint = getattr(route, "endpoint", None)
        module = str(getattr(endpoint, "__module__", ""))
        path = str(getattr(route, "path", ""))
        methods = set(getattr(route, "methods", set()) or set())
        legacy_ui = module == "intelligence.ui"
        superseded = (
            path == LEGACY_US_PUBLIC_PATH and "POST" in methods
        ) or (
            path == LEGACY_COMPANY_PATH and "GET" in methods
        ) or (
            path == LEGACY_BOL_PATH and "GET" in methods
        )
        if legacy_ui and superseded:
            removed += 1
            continue
        kept.append(route)
    if removed:
        app.router.routes[:] = kept
    return removed
