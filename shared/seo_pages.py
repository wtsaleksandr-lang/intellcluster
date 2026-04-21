"""
Programmatic SEO page engine.

Generates landing pages for long-tail comparison queries like:
  /compare/hubspot-vs-salesforce-vs-pipedrive
  /compare/macbook-air-vs-thinkpad-x1

The pages are driven by data/compare_pages.json — edit that file to add more.
Each page renders a pre-built decision framework + CTA to customize via Phronesis.
"""

import json
import re
from pathlib import Path
from typing import Optional

DATA_DIR = Path("data")
COMPARE_FILE = DATA_DIR / "compare_pages.json"


def load_compare_pages() -> list[dict]:
    """Load the comparison pages data."""
    if not COMPARE_FILE.exists():
        return []
    try:
        with open(COMPARE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def slugify(text: str) -> str:
    """Convert an option name to a URL-safe slug."""
    s = re.sub(r"[^\w\s-]", "", text.lower())
    s = re.sub(r"[-\s]+", "-", s).strip("-")
    return s


def page_slug(options: list[str]) -> str:
    """Build a slug from a list of option names: HubSpot vs Salesforce -> hubspot-vs-salesforce."""
    return "-vs-".join(slugify(o) for o in options)


def get_compare_page(slug: str) -> Optional[dict]:
    """Look up a compare page by its slug."""
    for page in load_compare_pages():
        if page_slug(page.get("options", [])) == slug:
            return page
    return None


def all_compare_slugs() -> list[str]:
    """Return all compare page slugs (for sitemap generation)."""
    return [page_slug(p.get("options", [])) for p in load_compare_pages()]
