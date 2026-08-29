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
    mounted_modules: set[str] = set()
    for route in app.router.routes:
        endpoint = getattr(route, "endpoint", None)
        module = str(getattr(endpoint, "__module__", ""))
        path = str(getattr(route, "path", ""))
        if module:
            mounted_modules.add(module)
        if module == "intelligence.ui" and path in superseded:
            legacy.append(path)

    assert not legacy, legacy
    # Exact FastAPI path/module serialization has changed between dependency
    # versions, so route behavior is tested separately. Here we only guarantee
    # the focused canonical modules are mounted and the obsolete UI copies are not.
    assert "intelligence.api" in mounted_modules
    assert "intelligence.company_routes" in mounted_modules
    assert "intelligence.search_routes" in mounted_modules

    print("Route hardening checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())