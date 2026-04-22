"""Decision templates library — pre-filled starter decisions for Phronesis."""

import json
from pathlib import Path
from typing import Optional

DATA_FILE = Path("data") / "templates.json"


def load_templates() -> list[dict]:
    if not DATA_FILE.exists():
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def get_template(slug: str) -> Optional[dict]:
    for t in load_templates():
        if t.get("slug") == slug:
            return t
    return None


def templates_by_category() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for t in load_templates():
        cat = t.get("category", "Other")
        out.setdefault(cat, []).append(t)
    return out
