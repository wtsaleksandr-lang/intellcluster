from __future__ import annotations

import os

from fastapi.testclient import TestClient

from main_data import app
from shared.admin import ADMIN_COOKIE, create_admin_token


def run() -> int:
    anonymous = TestClient(app)
    page = anonymous.get("/admin/intelligence")
    assert page.status_code == 401
    audit = anonymous.get("/api/intelligence/admin/data-quality")
    assert audit.status_code == 401

    admin = TestClient(app)
    admin.cookies.set(
        ADMIN_COOKIE,
        create_admin_token(os.environ["ADMIN_USERNAME"]),
    )
    page = admin.get("/admin/intelligence")
    assert page.status_code == 200, page.text
    assert "Intelligence Operations" in page.text
    assert "Run data-quality audit" in page.text
    assert "No paid enrichment runs from this page" in page.text

    audit = admin.get("/api/intelligence/admin/data-quality")
    assert audit.status_code == 200, audit.text
    payload = audit.json()
    assert payload.get("network_calls") == 0
    assert payload.get("paid_sources_called") is False
    assert isinstance(payload.get("checks"), dict)

    print("Intelligence admin operations checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
