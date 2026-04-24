"""
Tavily retrieval provider.

One of two providers behind the Synthesis retrieval orchestrator. Tavily
is AI-optimised: it cleans + extracts main article content when
`include_raw_content=true` is set, giving us `full_content` to ground
citations with. Brave doesn't expose equivalent raw content, so Tavily
hits tend to be the richer-text sources in the merged list.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from synthesis.orchestrator.retrievers.base import RawResult


ENDPOINT = "https://api.tavily.com/search"
TIMEOUT_S = 18.0
CACHE_TTL_S = 1800
FULL_CONTENT_MAX_CHARS = 2000


_cache: dict[tuple[str, int], tuple[float, list[RawResult]]] = {}


def is_configured() -> bool:
    return bool(os.environ.get("TAVILY_API_KEY"))


def _clean_raw_content(text: str | None) -> str:
    """Collapse whitespace/newline runs, trim, cap length."""
    if not text:
        return ""
    import re as _re
    cleaned = _re.sub(r"[ \t]+", " ", text)
    cleaned = _re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) > FULL_CONTENT_MAX_CHARS:
        cleaned = cleaned[:FULL_CONTENT_MAX_CHARS].rstrip() + "…"
    return cleaned


async def search(query: str, max_results: int = 6) -> list[RawResult]:
    """Run a Tavily search. Never raises."""
    key = os.environ.get("TAVILY_API_KEY")
    if not key or not query.strip():
        return []

    cache_key = (query.strip().lower(), max_results)
    hit = _cache.get(cache_key)
    if hit and time.time() - hit[0] <= CACHE_TTL_S:
        return hit[1]

    payload = {
        "api_key": key,
        "query": query.strip()[:400],
        "max_results": max(1, min(10, max_results)),
        "include_answer": False,
        "include_raw_content": True,       # richer ground for citations
        "search_depth": "advanced",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            resp = await client.post(ENDPOINT, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        print(f"[retrievers.tavily] call failed: {str(e)[:200]}")
        return []

    results: list[RawResult] = []
    for r in (data.get("results") or [])[:max_results]:
        if not r.get("url"):
            continue
        raw_content = r.get("raw_content")
        results.append(RawResult(
            provider="tavily",
            title=(r.get("title") or "")[:240] or "(untitled)",
            url=r["url"],
            snippet=(r.get("content") or "")[:600],
            full_content=_clean_raw_content(raw_content) if raw_content else None,
            relevance=float(r.get("score") or 0.0),
            published=r.get("published_date"),
            query=query,
            raw=r,
        ))

    _cache[cache_key] = (time.time(), results)
    return results
