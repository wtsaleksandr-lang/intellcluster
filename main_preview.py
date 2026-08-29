"""Safe visual-preview entrypoint for IntellCluster.

This process deliberately ignores DATABASE_URL and uses its own SQLite fixture
DB. It is safe to run separately while the main Replit PostgreSQL ingestion is
active. Do not use this entrypoint for production.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ["INTELLIGENCE_PREVIEW"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ["INTELLIGENCE_DB_PATH"] = os.environ.get(
    "INTELLIGENCE_PREVIEW_DB_PATH", "data/intelligence-preview.db"
)

from intelligence.preview import seed_preview  # noqa: E402

preview_db = Path(os.environ["INTELLIGENCE_DB_PATH"])
if not preview_db.exists() or os.environ.get("INTELLIGENCE_PREVIEW_RESEED") == "1":
    seed_preview()

from main_data import app  # noqa: E402,F401
