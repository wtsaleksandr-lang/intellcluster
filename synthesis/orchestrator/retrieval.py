"""
Retrieval orchestrator.

Fans queries across all configured retrieval providers in parallel,
rank-fuses the results with Reciprocal Rank Fusion, dedupes by URL,
merges provenance, and returns a unified list of RetrievedSource.

Design
------
- Providers live in `retrievers/` (Tavily, Brave). Each one implements
  the same async `search(query, max_results) -> list[RawResult]` and
  `is_configured() -> bool`. None of them raise.
- The orchestrator runs configured providers in parallel per query, then
  in parallel across queries. Any single failure is swallowed; the rest
  contribute their results.
- Rank fusion uses RRF (Reciprocal Rank Fusion, k=60). For each URL:
      score = sum over providers of 1 / (k + rank_within_that_provider)
  URLs that appear in multiple providers get boosted — an implicit
  corroboration signal that also flows into source-quality scoring via
  domain diversity.
- `full_content` is preserved from whichever provider supplied it
  (currently only Tavily). Brave-only results fall back to the snippet.
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlparse

from synthesis.orchestrator.retrievers import (
    tavily as tavily_provider,
    brave as brave_provider,
    list_configured_providers,
)
from synthesis.orchestrator.retrievers.base import RawResult
from synthesis.orchestrator.scope import augment_query_with_scope
from synthesis.orchestrator.types import RetrievedSource, Scope, utc_now_iso


DEFAULT_MAX_RESULTS = 6
MAX_QUERIES_PER_PHASE = 3
RRF_K = 60                      # classic RRF dampening constant

# Re-exports kept for back-compat with existing imports / tests that
# reference these from the orchestrator module.
FULL_CONTENT_MAX_CHARS = tavily_provider.FULL_CONTENT_MAX_CHARS
_clean_raw_content = tavily_provider._clean_raw_content


# ────────── Helpers ──────────

def is_configured() -> bool:
    """True if ANY retrieval provider is usable this run."""
    return bool(list_configured_providers())


def _domain_of(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
        return host.lower().lstrip("www.")
    except Exception:
        return ""


def _provider_search_callables() -> dict[str, Any]:
    """Map provider name -> async search callable, filtered to configured ones."""
    candidates = {
        "tavily": tavily_provider.search,
        "brave":  brave_provider.search,
    }
    return {
        name: fn for name, fn in candidates.items()
        if {
            "tavily": tavily_provider.is_configured,
            "brave":  brave_provider.is_configured,
        }[name]()
    }


# ────────── Query planning ──────────

def _plan_queries(
    refined_prompt: str,
    phase_prompt: str,
    category: str,
    scope: Scope | None = None,
) -> list[str]:
    """Pick 1–3 search queries from the prompts.

    Heuristic — we reuse the already-refined prompts rather than invoke
    an LLM to plan. Tavily's + Brave's rankers handle the rest.

    When `scope` is present, the category-shaped secondary query gets
    augmented with region/timeframe hints (see scope.augment_query).
    """
    queries: list[str] = []

    base = (phase_prompt or refined_prompt or "").strip().replace("\n", " ")
    if base:
        queries.append(base[:350])

    category_hint = {
        "competitor_market_research": "competitors pricing market share 2026",
        "marketing_growth":           "best channels acquisition 2026",
        "product_offer_design":       "pricing benchmark examples 2026",
        "funnel_conversion":          "conversion rate benchmarks 2026",
        "comparison_evaluation":      "comparison review 2026",
        "ai_systems_automation":      "architecture benchmarks 2026",
        "deep_research":              "recent findings 2026",
        "decision_strategy":          "tradeoffs considerations 2026",
        "business_ideas_validation":  "market size demand validation 2026",
    }.get(category)

    if category_hint and refined_prompt:
        cat_query = f"{refined_prompt[:180]} {category_hint}"[:350]
        if scope is not None:
            cat_query = augment_query_with_scope(cat_query, scope)
        queries.append(cat_query)

    # Dedupe case-insensitively, cap at MAX_QUERIES_PER_PHASE.
    seen, out = set(), []
    for q in queries:
        k = q.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(q)
        if len(out) >= MAX_QUERIES_PER_PHASE:
            break
    return out


# ────────── Rank fusion ──────────

def _rrf_fuse(
    per_provider_results: dict[str, list[RawResult]],
) -> list[tuple[float, RawResult, list[str]]]:
    """Reciprocal Rank Fusion.

    Returns a list of (rrf_score, representative_RawResult, providers_agreeing)
    sorted by score desc. The representative is the first RawResult encountered
    for each URL — we prefer results with full_content when picking it so
    Tavily's raw_content doesn't get dropped in favour of a snippet-only hit.
    """
    # url -> {"score": float, "providers": list[str], "reps": list[RawResult]}
    by_url: dict[str, dict] = {}

    for provider, results in per_provider_results.items():
        for rank, r in enumerate(results):
            if not r.url:
                continue
            slot = by_url.setdefault(r.url, {"score": 0.0, "providers": [], "reps": []})
            slot["score"] += 1.0 / (RRF_K + rank)
            if provider not in slot["providers"]:
                slot["providers"].append(provider)
            slot["reps"].append(r)

    fused: list[tuple[float, RawResult, list[str]]] = []
    for url, slot in by_url.items():
        # Prefer the rep with full_content; fall back to the first one.
        rep = next((r for r in slot["reps"] if r.full_content), slot["reps"][0])
        fused.append((slot["score"], rep, slot["providers"]))

    fused.sort(key=lambda t: t[0], reverse=True)
    return fused


# ────────── Main orchestrator ──────────

async def _run_provider_fanout(
    query: str,
    per_query_max: int,
    query_idx: int = 0,
    total_queries: int = 1,
    on_progress=None,
) -> dict[str, list[RawResult]]:
    """Kick off every configured provider in parallel for one query."""
    providers = _provider_search_callables()
    if not providers:
        return {}
    names = list(providers.keys())

    async def _call(name: str, fn):
        if on_progress is not None:
            try:
                await on_progress({
                    "stage": "querying",
                    "provider": name,
                    "query": query,
                    "query_idx": query_idx,
                    "total_queries": total_queries,
                })
            except Exception:
                pass
        try:
            out = await fn(query, per_query_max)
        except Exception as e:
            if on_progress is not None:
                try:
                    await on_progress({
                        "stage": "returned",
                        "provider": name,
                        "query_idx": query_idx,
                        "count": 0,
                        "error": str(e)[:160],
                    })
                except Exception:
                    pass
            return e
        if on_progress is not None:
            try:
                await on_progress({
                    "stage": "returned",
                    "provider": name,
                    "query_idx": query_idx,
                    "count": len(out or []),
                })
            except Exception:
                pass
        return out

    tasks = [_call(name, providers[name]) for name in names]
    outputs = await asyncio.gather(*tasks, return_exceptions=True)

    merged: dict[str, list[RawResult]] = {}
    for name, out in zip(names, outputs):
        if isinstance(out, BaseException):
            print(f"[retrieval] provider {name} raised: {str(out)[:160]}")
            continue
        merged[name] = out or []
    return merged


async def retrieve_sources(
    refined_prompt: str,
    phase_prompt: str,
    category: str,
    max_sources: int = 10,
    start_id: int = 1,
    scope: Scope | None = None,
    on_progress=None,
    on_source_added=None,
) -> tuple[list[RetrievedSource], dict[str, Any]]:
    """Run planned searches across every configured provider, fuse + dedupe.

    Callbacks (all optional, all async, all exceptions swallowed):
      on_progress(dict):    per-provider query/return/fusing status
      on_source_added(dict): called once per final RetrievedSource, in
                              ranked order, after fusion. The dict is
                              the RetrievedSource.to_dict() shape.
    """
    configured = list_configured_providers()
    if not configured:
        return [], {"provider": "none", "providers_used": [], "queries": [], "configured": False}

    queries = _plan_queries(refined_prompt, phase_prompt, category, scope=scope)
    if not queries:
        return [], {"provider": "none", "providers_used": configured, "queries": [], "configured": True}

    # How many results per provider per query. We want a fused set roughly
    # max_sources big — asking for a little more per call gives room to
    # absorb duplicates.
    per_query_max = max(3, (max_sources // max(1, len(queries))) + 2)

    # Run each query across all providers in parallel. Collect per-provider
    # lists so fusion treats them as independent rankings.
    per_provider_lists: dict[str, list[RawResult]] = {}
    per_provider_counts: dict[str, int] = {}
    providers_returning: set[str] = set()

    results_per_query = await asyncio.gather(
        *[
            _run_provider_fanout(
                q, per_query_max,
                query_idx=i, total_queries=len(queries),
                on_progress=on_progress,
            )
            for i, q in enumerate(queries)
        ],
        return_exceptions=True,
    )

    for q, per_query_map in zip(queries, results_per_query):
        if isinstance(per_query_map, BaseException):
            continue
        for provider_name, results in per_query_map.items():
            if not results:
                continue
            providers_returning.add(provider_name)
            per_provider_lists.setdefault(provider_name, []).extend(results)
            per_provider_counts[provider_name] = per_provider_counts.get(provider_name, 0) + len(results)

    if not per_provider_lists:
        return [], {
            "provider": "none",
            "providers_used": configured,
            "providers_returning": [],
            "queries": queries,
            "configured": True,
        }

    # Within each provider list we dedupe by URL, preserving the best
    # (earliest = highest-ranked, or the one with full_content).
    deduped_per_provider: dict[str, list[RawResult]] = {}
    for provider_name, results in per_provider_lists.items():
        seen: dict[str, RawResult] = {}
        for r in results:
            if r.url not in seen:
                seen[r.url] = r
            else:
                # Keep whichever has full_content, otherwise the first.
                if not seen[r.url].full_content and r.full_content:
                    seen[r.url] = r
        deduped_per_provider[provider_name] = list(seen.values())

    if on_progress is not None:
        try:
            await on_progress({"stage": "fusing"})
        except Exception:
            pass

    fused = _rrf_fuse(deduped_per_provider)[:max_sources]

    # Promote the RRF score into .relevance (0..1 normalised on the max in
    # this batch so confidence / downstream logic stays on the same scale).
    max_score = max((s for s, _, _ in fused), default=1.0) or 1.0

    sources: list[RetrievedSource] = []
    enriched_count = 0
    now = utc_now_iso()

    for i, (score, rep, providers_agreeing) in enumerate(fused, start=start_id):
        if rep.full_content:
            enriched_count += 1
        normalised_relevance = min(1.0, score / max_score) if max_score else 0.0
        source = RetrievedSource(
            id=i,
            title=rep.title or "(untitled)",
            url=rep.url,
            domain=_domain_of(rep.url),
            published=rep.published,
            snippet=rep.snippet[:600] if rep.snippet else "",
            retrieved_at=now,
            relevance=round(normalised_relevance, 4),
            query=rep.query or "",
            full_content=rep.full_content,
            provider=rep.provider,
            providers_agreeing=list(providers_agreeing),
        )
        sources.append(source)
        if on_source_added is not None:
            try:
                await on_source_added(source.to_dict())
            except Exception:
                pass

    providers_returning_list = sorted(providers_returning)
    meta = {
        "provider": "+".join(providers_returning_list) if providers_returning_list else "none",
        "providers_used": configured,
        "providers_returning": providers_returning_list,
        "queries": queries,
        "configured": True,
        "enriched": enriched_count,
        "per_provider_counts": per_provider_counts,
    }
    return sources, meta


# ────────── Prompt formatting ──────────

def format_sources_for_prompt(sources: list[RetrievedSource]) -> str:
    """Compact numbered block downstream agents cite by [id].

    Prefers `full_content` (Tavily) for the body; falls back to snippet.
    """
    if not sources:
        return ""
    lines = [
        "## Retrieved Sources",
        "(cite these by their bracket id — do NOT invent any other sources)",
        "",
    ]
    for s in sources:
        date = f" · {s.published}" if s.published else ""
        lines.append(f"[{s.id}] {s.title} — {s.domain}{date}")
        lines.append(f"    {s.url}")
        body = s.full_content or s.snippet
        if body:
            limit = FULL_CONTENT_MAX_CHARS if s.full_content else 400
            lines.append(f"    {body[:limit]}")
        lines.append("")
    return "\n".join(lines)
