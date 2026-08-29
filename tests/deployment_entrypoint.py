from __future__ import annotations

import json
from pathlib import Path

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

    # Importing the deployment entrypoint must expose both core + intelligence routes.
    from main_data import app

    paths = {str(getattr(route, "path", "")) for route in app.router.routes}
    assert "/api/health" in paths
    assert "/api/intelligence/health" in paths
    assert "/data" in paths

    print("Deployment entrypoint checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
