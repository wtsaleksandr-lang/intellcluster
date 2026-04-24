"""
Brave Search retrieval provider.

Brave maintains an independent web index (not derived from Google or Bing),
which makes it a genuine diversity bet against Tavily. Trade-off: Brave
doesn't return cleaned full-article content — only title / URL / description.
Orchestrator still uses these hits; they just won't carry a `full_content`.

API reference
-------------
  GET https://api.search.brave.com/res/v1/web/search
       ?q=<query>&count=<n>
  Header: X-Subscription-Token: <key>

Response (abridged):
  { "web": { "results": [
      { "title": "...",
        "url": "...",
        "description": "...",
        "age": "6 days ago",       -- humanised age, not an ISO date
        "page_age": "2026-04-01",  -- sometimes present, ISO-ish
        "meta_url": { "hostname": "..." }
      }
  ]}}

Free tier: 2000 requests/month, 1 QPS. Set BRAVE_SEARCH_API_KEY to enable.
"""

from __future__ import annotations

import os
import re
import time

import httpx

from synthesis.orchestrator.retrievers.base import RawResult


ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
TIMEOUT_S = 12.0
CACHE_TTL_S = 1800


_cache: dict[tuple[str, int], tuple[float, list[RawResult]]] = {}


def is_configured() -> bool:
    return bool(os.environ.get("BRAVE_SEARCH_API_KEY"))


def _isoify_page_age(s: str | None) -> str | None:
    """Brave sometimes returns 'page_age' as ISO, sometimes a humanised age
    like '6 days ago'. Pass through an ISO-ish date; drop humanised ages."""
    if not s or not isinstance(s, str):
        return None
    # Match YYYY-MM-DD (optionally followed by a time). No trailing \b —
    # datestrings often abut a "Z" or "+00:00" which share the word class
    # with the seconds and would swallow the optional-time capture.
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})(?:[T\s]\d{2}:\d{2}:\d{2})?", s)
    return m.group(0) if m else None


async def search(query: str, max_results: int = 6) -> list[RawResult]:
    """Run a Brave search. Never raises."""
    key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not key or not query.strip():
        return []

    cache_key = (query.strip().lower(), max_results)
    hit = _cache.get(cache_key)
    if hit and time.time() - hit[0] <= CACHE_TTL_S:
        return hit[1]

    params = {
        "q": query.strip()[:400],
        "count": max(1, min(20, max_results)),
        "safesearch": "moderate",
        "text_decorations": "false",
    }
    headers = {
        "X-Subscription-Token": key,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            resp = await client.get(ENDPOINT, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        print(f"[retrievers.brave] call failed: {str(e)[:200]}")
        return []

    web_results = ((data.get("web") or {}).get("results") or [])
    results: list[RawResult] = []
    # Brave doesn't ship numeric scores; derive a descending pseudo-score
    # from rank so rank-fusion downstream still sees comparable signals.
    for rank, r in enumerate(web_results[:max_results]):
        url = r.get("url")
        if not url:
            continue
        meta = r.get("meta_url") or {}
        published = _isoify_page_age(r.get("page_age") or r.get("age"))
        # Synthesise a 0..1 relevance that decays with rank.
        pseudo_relevance = max(0.0, 1.0 - (rank * 0.08))
        results.append(RawResult(
            provider="brave",
            title=(r.get("title") or "")[:240] or "(untitled)",
            url=url,
            snippet=(r.get("description") or "")[:600],
            full_content=None,   # Brave doesn't provide full-text extraction
            relevance=pseudo_relevance,
            published=published,
            query=query,
            raw={
                "rank": rank,
                "hostname": meta.get("hostname"),
                "favicon": meta.get("favicon"),
            },
        ))

    _cache[cache_key] = (time.time(), results)
    return results
