from __future__ import annotations

from fastapi.testclient import TestClient

from main_data import app


client = TestClient(app)


def _assert_navigation(path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200, response.text
    assert response.text.count('data-intelligence-nav="desktop"') == 1
    assert response.text.count('data-intelligence-nav="mobile"') == 1
    assert response.text.count('data-intelligence-nav="footer"') == 1
    assert '<a href="/data" class="nav-tool"' in response.text
    assert ">Business Intelligence</a>" in response.text


def run() -> int:
    _assert_navigation("/")
    _assert_navigation("/pricing")

    data = client.get("/data")
    assert data.status_code == 200, data.text
    # The wrapper is idempotent even on the separate intelligence template stack.
    assert data.text.count('data-intelligence-nav="desktop"') <= 1

    print("Launch navigation checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
