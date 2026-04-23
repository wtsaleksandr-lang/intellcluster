"""
Blog loader.

Reads Markdown files from `content/blog/*.md`, each with a YAML-style
frontmatter block delimited by `---` lines at the top of the file.

Required frontmatter fields:

    title          Human-readable title
    slug           URL slug (falls back to filename stem)
    publish_date   ISO date (YYYY-MM-DD). Posts with future dates are hidden.
    meta_desc      <= 160 char description for SEO

Optional:

    tags           Comma-separated list — e.g. "decision-science, ai"
    tool_focus     "phronesis" | "synthesis" | "both"   (drives hero palette)
    hero_keywords  Comma-separated keywords rendered as chips on the OG card
    reading_time   Integer minutes (auto-estimated if omitted)
    author         Display name
    hero_tag       Short kicker text shown at the top of the OG card
    updated_date   ISO date — if present, surfaced in JSON-LD dateModified

Design note: we keep this tiny and stdlib-only (plus `markdown`) so publishing
is just `git push` — no admin UI, no DB, no background worker. "Scheduling" is
the publish_date filter on read; future posts stay invisible until their day.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

import markdown as _md

CONTENT_DIR = Path("content/blog")

# Module-level cache. The loader reads every .md file once on first access.
# Set _CACHE_MODE = "dev" via env if you want re-reads per call (not wired —
# trivial to add if we need it). For production the monolith restarts on
# deploy, which is when new articles ship anyway.
_POSTS_CACHE: list[dict[str, Any]] | None = None


def _parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    """Split a .md file into (metadata dict, markdown body)."""
    if not raw.startswith("---"):
        return {}, raw
    # Strip the leading fence, then split on the closing fence.
    rest = raw[3:]
    if "\n---" not in rest:
        return {}, raw
    header, _, body = rest.partition("\n---")
    meta: dict[str, Any] = {}
    for line in header.splitlines():
        line = line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")
        if key == "tags":
            meta[key] = [t.strip() for t in value.split(",") if t.strip()]
        elif key == "hero_keywords":
            meta[key] = [t.strip() for t in value.split(",") if t.strip()]
        elif key == "reading_time":
            try:
                meta[key] = int(value)
            except ValueError:
                meta[key] = 0
        elif key in ("publish_date", "updated_date"):
            try:
                meta[key] = _dt.date.fromisoformat(value)
            except ValueError:
                meta[key] = None
        else:
            meta[key] = value
    body = body.lstrip("\n")
    return meta, body


def _render_markdown(body: str) -> str:
    return _md.markdown(
        body,
        extensions=["extra", "toc", "sane_lists", "smarty"],
        output_format="html5",
    )


def _estimate_reading_time(body: str) -> int:
    words = len([w for w in body.split() if w])
    return max(1, round(words / 220))


def _load_all() -> list[dict[str, Any]]:
    global _POSTS_CACHE
    if _POSTS_CACHE is not None:
        return _POSTS_CACHE

    posts: list[dict[str, Any]] = []
    if not CONTENT_DIR.exists():
        _POSTS_CACHE = posts
        return posts

    for path in sorted(CONTENT_DIR.glob("*.md")):
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception as e:
            print(f"[blog] failed to read {path}: {e}")
            continue
        meta, body = _parse_frontmatter(raw)
        slug = (meta.get("slug") or path.stem).strip()
        posts.append({
            "slug": slug,
            "title": meta.get("title", slug),
            "meta_desc": meta.get("meta_desc", ""),
            "publish_date": meta.get("publish_date"),
            "updated_date": meta.get("updated_date"),
            "tags": meta.get("tags", []),
            "hero_keywords": meta.get("hero_keywords", []),
            "hero_tag": meta.get("hero_tag", "FIELD NOTES"),
            "tool_focus": meta.get("tool_focus", "both"),
            "reading_time": meta.get("reading_time") or _estimate_reading_time(body),
            "author": meta.get("author", "IntellCluster"),
            "body_html": _render_markdown(body),
        })

    _POSTS_CACHE = posts
    return posts


def list_published(include_future: bool = False) -> list[dict[str, Any]]:
    """Return published posts, newest first."""
    today = _dt.date.today()
    posts = _load_all()
    if not include_future:
        posts = [p for p in posts if p.get("publish_date") and p["publish_date"] <= today]
    return sorted(
        posts,
        key=lambda p: p.get("publish_date") or _dt.date.min,
        reverse=True,
    )


def get_post(slug: str) -> dict[str, Any] | None:
    """Look up a single post by slug. Hidden until publish_date."""
    today = _dt.date.today()
    for p in _load_all():
        if p["slug"] == slug and p.get("publish_date") and p["publish_date"] <= today:
            return p
    return None


def list_by_tag(tag: str) -> list[dict[str, Any]]:
    tag_l = tag.lower().strip()
    return [p for p in list_published() if tag_l in [t.lower() for t in p.get("tags", [])]]


def all_tags() -> list[tuple[str, int]]:
    """Return (tag, count) pairs sorted by count desc."""
    counts: dict[str, int] = {}
    for p in list_published():
        for t in p.get("tags", []):
            counts[t] = counts.get(t, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def all_slugs_for_sitemap() -> list[str]:
    return [p["slug"] for p in list_published()]
