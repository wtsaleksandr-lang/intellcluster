from __future__ import annotations

from fastapi.testclient import TestClient

from main_data import app


client = TestClient(app)


def run() -> int:
    response = client.get(
        "/data/search?q=DefinitelyNoSuchIntellClusterCompanyZXQ987654321"
    )
    assert response.status_code == 200
    text = response.text
    assert "No matching company profiles were found." in text
    assert "No matching business profiles found" in text
    assert "Preview fallback — no live rows matched this query." not in text
    assert "Maple Auto Supply Inc." not in text
    assert '<meta name="robots" content="noindex,follow">' in text

    legacy_demo = client.get("/data/company/maple-auto-supply-inc")
    assert legacy_demo.status_code == 404
    assert "No indexed profile" in legacy_demo.text
    assert '<meta name="robots" content="noindex,follow">' in legacy_demo.text

    print("Search empty-state checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
