"""
Per-source quality scoring.

Produces a SourceQuality with seven 0–1 components plus an `overall` score.
Everything is heuristic and deterministic — no LLM call. This keeps scoring
fast, cheap, and auditable. The goal isn't perfect; it's to separate
obvious-high (gov, primary research, recent major outlet) from
obvious-low (affiliate roundups, SEO spam, 2017 blog) so the strategist
and DM can weight citations sensibly.

Dimensions
----------
authority       Domain reputation (tier lookup + TLD)
recency         Days since published (linear within 3 years, floor beyond)
relevance       Pass-through from retrieval provider (Tavily score)
originality     Snippet distinctiveness across the batch (rough dedupe)
corroboration   How many OTHER sources in batch cover same domain cluster / topic
bias_risk       0 = clean, 1 = high affiliate/SEO/listicle risk
                (Higher is WORSE — the aggregator inverts it)
directness      Primary source (gov, company, paper) vs secondary (blog, news)
overall         Weighted aggregate, 0–1

Overall weights were picked to prefer authority + recency + relevance,
and to penalise bias_risk hardest. Tune via SQ_WEIGHTS without touching
callers.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from synthesis.orchestrator.types import RetrievedSource, SourceQuality


# ─── Domain reputation tiers ───

# Curated; add sparingly. Unknown domains get a neutral 0.5.
HIGH_AUTHORITY_SUFFIXES = (
    ".gov", ".edu", ".mil", ".int",
    ".who.int", ".un.org",
)

HIGH_AUTHORITY_DOMAINS: set[str] = {
    "nature.com", "science.org", "sciencedirect.com", "nejm.org",
    "thelancet.com", "pubmed.ncbi.nlm.nih.gov", "arxiv.org",
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk",
    "ft.com", "wsj.com", "nytimes.com", "economist.com",
    "bloomberg.com", "washingtonpost.com", "theguardian.com",
    "npr.org", "propublica.org",
    "hbr.org", "mckinsey.com", "bain.com", "bcg.com",
    "oecd.org", "worldbank.org", "imf.org", "iea.org",
    "sec.gov", "federalreserve.gov", "ec.europa.eu",
    "stripe.com", "openai.com", "anthropic.com", "google.com",
    "microsoft.com", "apple.com", "meta.com", "nvidia.com",
    "wikipedia.org",
    "techcrunch.com", "theverge.com", "wired.com", "arstechnica.com",
    "404media.co", "platformer.news", "stratechery.com",
}

MEDIUM_AUTHORITY_DOMAINS: set[str] = {
    "medium.com", "substack.com", "dev.to", "hashnode.dev",
    "stackoverflow.com", "stackexchange.com", "github.com",
    "github.io", "gitlab.com",
    "reddit.com", "news.ycombinator.com", "lobste.rs",
    "producthunt.com", "indiehackers.com",
    "forbes.com", "businessinsider.com", "cnbc.com",
    "venturebeat.com", "fastcompany.com", "inc.com",
    "mashable.com", "engadget.com", "zdnet.com", "cnet.com",
}

# Red-flag patterns for listicle / affiliate / SEO farm.
LOW_QUALITY_DOMAIN_HINTS = (
    "top10", "best-", "review-", "-review.com", "affiliate",
    "coupons", "deals-", "-deals.com", "compare-",
)

# Listicle + affiliate URL patterns.
AFFILIATE_URL_MARKERS = re.compile(
    r"(?:\?|&)(?:ref|aff|affid|utm_source=affiliate|tag=)[=_]",
    re.IGNORECASE,
)

LISTICLE_TITLE_MARKERS = re.compile(
    r"^\s*\d+\s+(?:best|top|greatest|cheapest|most)\b",
    re.IGNORECASE,
)


# ─── Scoring helpers ───

def _authority(domain: str) -> float:
    if not domain:
        return 0.4
    d = domain.lower()
    if any(d.endswith(suf) for suf in HIGH_AUTHORITY_SUFFIXES):
        return 0.95
    if d in HIGH_AUTHORITY_DOMAINS or any(d.endswith("." + h) for h in HIGH_AUTHORITY_DOMAINS):
        return 0.85
    if d in MEDIUM_AUTHORITY_DOMAINS or any(d.endswith("." + h) for h in MEDIUM_AUTHORITY_DOMAINS):
        return 0.55
    if any(hint in d for hint in LOW_QUALITY_DOMAIN_HINTS):
        return 0.25
    return 0.5


def _recency(published_iso: str | None) -> float:
    """0 (>=3y old / unknown) to 1.0 (published today)."""
    if not published_iso:
        return 0.4   # Unknown date — lean neutral-low, not zero.
    try:
        # Accept "2025-04-12", "2025-04-12T00:00:00Z", etc.
        s = published_iso.replace("Z", "+00:00")
        # If only a date, pad.
        if len(s) == 10:
            dt = datetime.fromisoformat(s + "T00:00:00+00:00")
        else:
            dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        return 0.4

    days = (datetime.now(timezone.utc) - dt).days
    if days <= 0:
        return 1.0
    if days >= 365 * 3:
        return 0.1
    # linear decay over 3 years, 1.0 → 0.1
    return max(0.1, 1.0 - (days / (365 * 3)) * 0.9)


def _originality(snippet: str, snippet_counter: Counter) -> float:
    """Penalise snippets that are very similar across the batch.

    Cheap proxy: take 6-word shingles and check how many other sources
    share any shingle. More shared = lower originality.
    """
    if not snippet or len(snippet) < 40:
        return 0.5
    words = re.findall(r"\w+", snippet.lower())
    if len(words) < 8:
        return 0.5
    shingles = {" ".join(words[i:i + 6]) for i in range(0, len(words) - 5, 3)}
    shared = sum(1 for sh in shingles if snippet_counter[sh] > 1)
    ratio = shared / max(1, len(shingles))
    # 0 shared → 1.0 ; 50% shared → 0.5 ; 100% shared → 0.1
    return max(0.1, 1.0 - ratio)


def _corroboration(domain: str, domain_counter: Counter, total: int) -> float:
    """Cross-source support: proxy = how many distinct domains exist beyond this one.

    If there are 6 other distinct domains covering this query, corroboration is high.
    If this source is the only one, corroboration is low.
    """
    if total <= 1:
        return 0.3
    distinct_other_domains = sum(1 for d, c in domain_counter.items() if d != domain and c > 0)
    # 0 → 0.2 ; 5+ → 1.0
    return min(1.0, 0.2 + 0.16 * distinct_other_domains)


def _bias_risk(url: str, title: str, domain: str) -> float:
    """0 = clean, 1 = affiliate/listicle/SEO-heavy. Higher = worse."""
    risk = 0.0
    if AFFILIATE_URL_MARKERS.search(url or ""):
        risk += 0.5
    if LISTICLE_TITLE_MARKERS.search(title or ""):
        risk += 0.3
    if any(hint in (domain or "").lower() for hint in LOW_QUALITY_DOMAIN_HINTS):
        risk += 0.3
    return min(1.0, risk)


def _directness(domain: str) -> float:
    """Primary (first-hand) vs secondary (commentary) sources."""
    if not domain:
        return 0.4
    d = domain.lower()
    if any(d.endswith(suf) for suf in HIGH_AUTHORITY_SUFFIXES):
        return 0.9       # gov / edu / int → primary
    if d in {"arxiv.org", "pubmed.ncbi.nlm.nih.gov", "nature.com", "science.org"}:
        return 0.95      # primary research
    if d in HIGH_AUTHORITY_DOMAINS:
        return 0.65      # reputable news / firm = secondary but reliable
    if d in MEDIUM_AUTHORITY_DOMAINS:
        return 0.45      # blogs / forums / medium
    return 0.4


# Aggregate weights. Sum does not need to be 1; we renormalise.
SQ_WEIGHTS = {
    "authority":      0.25,
    "recency":        0.20,
    "relevance":      0.15,
    "originality":    0.10,
    "corroboration":  0.10,
    "directness":     0.10,
    # bias_risk is subtracted (inverted) with weight below
    "bias_risk":      0.10,
}


def score_source(
    source: RetrievedSource,
    snippet_shingle_counter: Counter,
    domain_counter: Counter,
    total_sources: int,
) -> SourceQuality:
    authority = _authority(source.domain)
    recency = _recency(source.published)
    relevance = max(0.0, min(1.0, source.relevance))
    originality = _originality(source.snippet, snippet_shingle_counter)
    corroboration = _corroboration(source.domain, domain_counter, total_sources)
    bias_risk = _bias_risk(source.url, source.title, source.domain)
    directness = _directness(source.domain)

    w = SQ_WEIGHTS
    weighted_positive = (
        w["authority"] * authority +
        w["recency"] * recency +
        w["relevance"] * relevance +
        w["originality"] * originality +
        w["corroboration"] * corroboration +
        w["directness"] * directness
    )
    positive_weight_sum = sum(v for k, v in w.items() if k != "bias_risk")
    positive = weighted_positive / positive_weight_sum

    overall = max(0.0, min(1.0, positive - w["bias_risk"] * bias_risk))

    return SourceQuality(
        authority=round(authority, 3),
        recency=round(recency, 3),
        relevance=round(relevance, 3),
        originality=round(originality, 3),
        corroboration=round(corroboration, 3),
        bias_risk=round(bias_risk, 3),
        directness=round(directness, 3),
        overall=round(overall, 3),
    )


def score_sources(sources: list[RetrievedSource]) -> dict[int, SourceQuality]:
    """Score an entire batch. Returns {source.id: SourceQuality}."""
    if not sources:
        return {}

    # Pre-compute batch-level counters (originality + corroboration)
    snippet_shingles: Counter = Counter()
    for s in sources:
        words = re.findall(r"\w+", (s.snippet or "").lower())
        if len(words) < 8:
            continue
        shingles = {" ".join(words[i:i + 6]) for i in range(0, len(words) - 5, 3)}
        for sh in shingles:
            snippet_shingles[sh] += 1

    domain_counter: Counter = Counter(s.domain for s in sources if s.domain)

    return {
        s.id: score_source(s, snippet_shingles, domain_counter, len(sources))
        for s in sources
    }
