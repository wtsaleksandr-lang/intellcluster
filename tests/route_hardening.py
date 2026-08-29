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
    for route in app.router.routes:
        endpoint = getattr(route, "endpoint", None)
        module = str(getattr(endpoint, "__module__", ""))
        path = str(getattr(route, "path", ""))
        if module == "intelligence.ui" and path in superseded:
            legacy.append(path)

    # FastAPI/Starlette can wrap route endpoints in ways that make endpoint-module
    # introspection version-dependent. Actual canonical behavior is covered by
    # tests.company_routes, tests.intelligence_api and tests.search_empty_state.
    # This check has one stable job: ensure the obsolete UI registrations are gone.
    assert not legacy, legacy

    print("Route hardening checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())