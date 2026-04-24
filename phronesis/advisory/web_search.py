"""
Web search integration for the Evidence Agent.

This is SCAFFOLDING — the code path activates only when a Tavily API key
is present in the environment. Without `TAVILY_API_KEY` set, `search()`
returns an empty list and the Evidence Agent behaves exactly as before
(flagging unknown facts as missing instead of fabricating them).

Why Tavily? It's the cleanest AI-optimised search API: one endpoint,
one key, no browser fingerprinting, explicit `max_results` + content
snippets, $0.001 per call. Alternatives like Brave Search API or
Serper.dev work too — the shape below is easy to swap.

SETUP (to activate)
-------------------
1. Sign up at https://tavily.com — 1000 free searches/month on free tier
2. Set TAVILY_API_KEY in Replit Secrets
3. Restart the app
4. That's it. The Evidence Agent's system prompt will include web search
   results automatically the next time it runs.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


TAVILY_ENDPOINT = "https://api.tavily.com/search"
SEARCH_TIMEOUT_S = 12.0
DEFAULT_MAX_RESULTS = 5


def is_configured() -> bool:
    """True if web search is available this run."""
    return bool(os.environ.get("TAVILY_API_KEY"))


async def search(
    query: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    include_raw_content: bool = False,
) -> list[dict[str, Any]]:
    """
    Run a web search. Returns a list of result dicts like:
        [{"title": "...", "url": "...", "content": "...", "score": 0.82}]

    Returns [] when:
      - TAVILY_API_KEY is not set
      - Network / API failure (never raises — the advisory pipeline
        must keep running even if search is down)
      - Empty query

    Caller is responsible for formatting results into the Evidence Agent
    prompt; see `format_for_prompt()` below.
    """
    key = os.environ.get("TAVILY_API_KEY")
    if not key or not query.strip():
        return []

    payload = {
        "api_key": key,
        "query": query.strip()[:400],
        "max_results": max(1, min(10, max_results)),
        "include_answer": False,
        "include_raw_content": include_raw_content,
        "search_depth": "basic",
    }
    try:
        async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT_S) as client:
            resp = await client.post(TAVILY_ENDPOINT, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        print(f"[web_search] Tavily call failed: {str(e)[:200]}")
        return []

    results = []
    for r in (data.get("results") or [])[:max_results]:
        if not r.get("url"):
            continue
        results.append({
            "title": (r.get("title") or "")[:200],
            "url": r["url"],
            "content": (r.get("content") or "")[:600],
            "score": float(r.get("score") or 0.0),
        })
    return results


def format_for_prompt(results: list[dict[str, Any]]) -> str:
    """Turn search results into a prompt fragment the Evidence Agent can cite."""
    if not results:
        return ""
    lines = [
        "WEB SEARCH RESULTS (use only if directly relevant; cite the URL when you do):",
        "",
    ]
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r['title']}")
        lines.append(f"    {r['url']}")
        if r.get("content"):
            lines.append(f"    {r['content'][:300]}")
        lines.append("")
    return "\n".join(lines)


def infer_search_queries(session) -> list[str]:
    """
    Decide what to search for given an advisory session. Conservative:
    0-2 queries max, only when the question clearly involves external facts.

    Returns empty list when web search wouldn't materially improve evidence
    quality (e.g. personal / emotional decisions with no factual anchors).
    """
    intake = session.intake
    if not intake:
        return []

    category = (session.category or "").lower()
    # Personal / exploratory calls rarely benefit from web search — those
    # are usually internal-evidence decisions.
    if category in ("personal", "exploratory"):
        return []

    # Build queries from option names + category context
    queries: list[str] = []
    options = (intake.options or [])[:3]
    question = intake.advisory_question or session.raw_input

    if len(options) >= 2:
        # "OptionA vs OptionB review 2026" — captures comparison pages
        q = " vs ".join(options[:3]) + " comparison review 2026"
        queries.append(q[:400])

    # Category-specific secondary query
    if category in ("purchase", "vendor") and options:
        queries.append(f"{options[0]} vs {options[1] if len(options)>1 else 'alternatives'} 2026 tradeoffs"[:400])
    elif category in ("business", "strategic"):
        queries.append(f"{question[:150]} tradeoffs 2026")
    elif category == "finance":
        queries.append(f"{question[:150]} historical return risk")

    # Dedupe, cap at 2
    seen = set()
    out = []
    for q in queries:
        k = q.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(q)
        if len(out) >= 2:
            break
    return out
