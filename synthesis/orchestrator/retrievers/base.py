"""
Shared types for retrieval providers.

RawResult is the uniform shape every provider returns. The orchestrator
converts RawResult into the richer RetrievedSource (with stable ids,
domain, quality scores, etc.) after fusion.

Providers MUST NOT raise. Any failure -> return [].
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RawResult:
    """One raw search hit, before fusion + quality scoring.

    provider:        "tavily" | "brave" | ...
    title:           page title (short)
    url:             canonical URL (used as the dedupe key)
    snippet:         short excerpt, typically the search-engine teaser
    full_content:    extracted main article text if the provider gives it
                     (Tavily yes, Brave no — None when unavailable)
    relevance:       provider-supplied score, 0..1 (normalised at ingest)
    published:       ISO date string if the provider has one
    query:           the query string that surfaced this hit
    raw:             full raw response dict (kept for debugging only)
    """
    provider: str
    title: str
    url: str
    snippet: str
    full_content: str | None = None
    relevance: float = 0.0
    published: str | None = None
    query: str = ""
    raw: dict = field(default_factory=dict)
