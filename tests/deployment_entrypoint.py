from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def run() -> int:
    procfile = (ROOT / "Procfile").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    replit = (ROOT / ".replit").read_text(encoding="utf-8")
    railway = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))

    assert "main_data:app" in procfile
    assert "main:app" not in procfile.replace("main_data:app", "")

    assert "main_data:app" in dockerfile
    assert "uvicorn main:app" not in dockerfile

    assert "main_data:app" in replit
    assert '"main_data:app"' in replit

    start_command = str(railway.get("deploy", {}).get("startCommand") or "")
    assert "main_data:app" in start_command
    assert "uvicorn main:app" not in start_command

    # Request through the actual deployment entrypoint rather than relying on
    # route-list internals. This confirms both the core product and intelligence
    # directory are reachable from the same ASGI application.
    from main_data import app

    client = TestClient(app)
    core = client.get("/api/health")
    assert core.status_code == 200, core.text
    data = client.get("/data")
    assert data.status_code == 200, data.text
    intelligence = client.get("/api/intelligence/health")
    assert intelligence.status_code == 200, intelligence.text
    assert intelligence.json().get("status") == "ok"

    print("Deployment entrypoint checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
