from __future__ import annotations

from main_data import app


def run() -> int:
    legacy = []
    for route in app.router.routes:
        path = str(getattr(route, "path", ""))
        endpoint = getattr(route, "endpoint", None)
        module = str(getattr(endpoint, "__module__", ""))
        if "enrich/us-public" in path and module == "intelligence.ui":
            legacy.append(path)

    assert not legacy, legacy
    # Canonical route behavior itself is covered by tests.intelligence_api; this
    # regression specifically guarantees the obsolete UI-layer copy is gone.
    print("Route hardening checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
