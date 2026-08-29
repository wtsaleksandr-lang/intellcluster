from __future__ import annotations

from typing import Any

LEGACY_US_PUBLIC_PATH = "/api/intelligence/company/{slug}/enrich/us-public"
LEGACY_COMPANY_PATH = "/data/company/{slug}"
LEGACY_BOL_PATH = "/data/company/{slug}/bol/{bol_number}"
LEGACY_SEARCH_PATH = "/data/search"


def prune_shadowed_legacy_routes(app: Any) -> int:
    """Remove routes that focused modules replace later in ``main_data``.

    FastAPI/Starlette versions may wrap endpoint callables, so endpoint-module
    metadata is not reliable enough for pruning. At this point in application
    startup the focused company/search routes have not been mounted yet, which
    makes it safe to remove the historical GET registrations by exact path.

    The U.S. enrichment API is different: its canonical implementation is already
    mounted by ``main_data_core`` before the legacy UI copy. Keep the first matching
    POST route and drop later duplicates, independent of endpoint wrapper details.
    """
    kept = []
    removed = 0
    seen_us_public = False
    page_paths = {LEGACY_COMPANY_PATH, LEGACY_BOL_PATH, LEGACY_SEARCH_PATH}

    for route in app.router.routes:
        path = str(getattr(route, "path", ""))
        methods = set(getattr(route, "methods", set()) or set())

        if path in page_paths and "GET" in methods:
            removed += 1
            continue

        if path == LEGACY_US_PUBLIC_PATH and "POST" in methods:
            if seen_us_public:
                removed += 1
                continue
            seen_us_public = True

        kept.append(route)

    if removed:
        app.router.routes[:] = kept
    return removed
