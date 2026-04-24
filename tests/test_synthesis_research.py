"""
Unit tests for the new Synthesis research layer:

  - retrieval (graceful fallback, query planning, domain extraction)
  - source_quality (authority tiers, recency, bias_risk, aggregate)
  - confidence (band mapping, redistribution when no sources)
  - report_schema (JSON parsing, citation sanitisation, text fallback)

No network calls — Tavily calls are gated on TAVILY_API_KEY which we
make sure is unset in the retrieval tests.

Run:
    python -m tests.test_synthesis_research
    # or pytest -q tests/test_synthesis_research.py
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from collections import Counter
from pathlib import Path


# Ensure repo root importable + UTF-8 stdout (Windows cp1252 otherwise)
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


# Ensure tavily key is unset for graceful-fallback tests
os.environ.pop("TAVILY_API_KEY", None)


# ───── Imports from the new modules ─────
from synthesis.orchestrator.types import (
    RetrievedSource,
    ConfidenceScore,
    Scope,
)
from synthesis.orchestrator import retrieval
from synthesis.orchestrator.retrievers import (
    base as retrievers_base,
    brave as brave_provider,
    tavily as tavily_provider,
)
from synthesis.orchestrator.retrievers import list_configured_providers
from synthesis.orchestrator.source_quality import (
    _authority,
    _recency,
    _bias_risk,
    score_sources,
)
from synthesis.orchestrator.confidence import compute_confidence
from synthesis.orchestrator import report_schema
from synthesis.orchestrator import scope as scope_mod


# ───── Helpers ─────

def _src(id_, title, url, published=None, snippet="some snippet content for testing", relevance=0.7):
    return RetrievedSource(
        id=id_,
        title=title,
        url=url,
        domain=retrieval._domain_of(url),
        published=published,
        snippet=snippet,
        retrieved_at="2026-04-23T00:00:00+00:00",
        relevance=relevance,
        query="test query",
    )


checks = []


def check(name, cond, detail=""):
    checks.append((name, bool(cond), detail))
    prefix = "PASS" if cond else "FAIL"
    suffix = f" — {detail}" if detail and not cond else ""
    print(f"  {prefix}: {name}{suffix}")


# ───── Retrieval module ─────

def test_retrieval_graceful_fallback():
    print("\n[retrieval] graceful fallback when TAVILY_API_KEY is unset")
    check("is_configured() returns False when key missing", not retrieval.is_configured())

    sources, meta = asyncio.run(retrieval.retrieve_sources(
        refined_prompt="What's the best AI coding assistant in 2026?",
        phase_prompt="Compare Cursor, Copilot, Claude Code.",
        category="comparison_evaluation",
    ))
    check("returns empty source list without key", sources == [])
    check("meta.configured is False", meta.get("configured") is False)
    check("meta.provider is 'none'", meta.get("provider") == "none")


def test_domain_extraction():
    print("\n[retrieval] domain extraction")
    check("plain domain", retrieval._domain_of("https://example.com/path") == "example.com")
    check("www stripped", retrieval._domain_of("https://www.nature.com/articles/x").replace("www.", "") == "nature.com")
    check("malformed returns empty", retrieval._domain_of("not a url") in ("", "not a url"))


def test_query_planning():
    print("\n[retrieval] query planning")
    queries = retrieval._plan_queries(
        refined_prompt="What are the best AI coding assistants?",
        phase_prompt="Compare top AI coding assistants on price and features.",
        category="comparison_evaluation",
    )
    check("produces 1-3 queries", 1 <= len(queries) <= 3, f"got {len(queries)}")
    check("first query is phase-prompt-based", queries[0].startswith("Compare"))
    check("category-specific query present", any("comparison review" in q.lower() for q in queries))


def test_sources_prompt_format():
    print("\n[retrieval] format_sources_for_prompt")
    sources = [_src(1, "Nature paper on X", "https://nature.com/article/x", "2025-11-01")]
    block = retrieval.format_sources_for_prompt(sources)
    check("contains the cite instruction", "cite these by their bracket id" in block)
    check("contains source id", "[1]" in block)
    check("contains URL", "https://nature.com/article/x" in block)
    check("empty block on empty list", retrieval.format_sources_for_prompt([]) == "")


# ───── Full-content enrichment (upgrade #1) ─────

def test_clean_raw_content_hygiene():
    print("\n[retrieval] _clean_raw_content hygiene")
    # Tabs + spaces collapse, triple newlines collapse, leading/trailing trimmed.
    messy = "  Hello   world\t\there.\n\n\n\nNext para  .  \n\n\n\n\nEnd.  "
    cleaned = retrieval._clean_raw_content(messy)
    check("runs of spaces collapsed", "   " not in cleaned)
    check("triple+ newlines collapsed to two", "\n\n\n" not in cleaned)
    check("leading/trailing whitespace stripped", cleaned == cleaned.strip())
    check("body preserved", "Next para" in cleaned and "End." in cleaned)
    check("empty input returns empty", retrieval._clean_raw_content("") == "")
    check("None input handled", retrieval._clean_raw_content(None) == "")


def test_clean_raw_content_truncation():
    print("\n[retrieval] _clean_raw_content truncation")
    long_text = "x" * (retrieval.FULL_CONTENT_MAX_CHARS + 500)
    cleaned = retrieval._clean_raw_content(long_text)
    # Cleaned len = MAX + 1 (the ellipsis char replacing the tail)
    check("truncated to cap + ellipsis", len(cleaned) <= retrieval.FULL_CONTENT_MAX_CHARS + 1)
    check("ends with ellipsis", cleaned.endswith("…"))

    short_text = "x" * 100
    short_cleaned = retrieval._clean_raw_content(short_text)
    check("short text not truncated", short_cleaned == short_text)
    check("short text has no ellipsis", not short_cleaned.endswith("…"))


def test_format_uses_full_content_when_present():
    print("\n[retrieval] format_sources_for_prompt uses full_content when present")
    rich_body = "Detailed article body. " * 30          # ~690 chars
    s_rich = _src(1, "Rich source", "https://example.com/a")
    s_rich.full_content = rich_body
    s_plain = _src(2, "Plain source", "https://example.com/b")
    # s_plain.full_content stays None (default)

    block = retrieval.format_sources_for_prompt([s_rich, s_plain])
    check("rich source body appears", "Detailed article body." in block)
    check("plain source falls back to snippet", "some snippet content" in block)
    # Full_content gets the bigger allowance; snippet stays capped at 400.
    check("rich body longer than 400 char snippet allowance",
          block.count("Detailed article body.") > 10)


def test_format_truncates_full_content_to_limit():
    print("\n[retrieval] format truncates full_content to FULL_CONTENT_MAX_CHARS")
    huge = "y" * (retrieval.FULL_CONTENT_MAX_CHARS + 10000)
    s = _src(1, "Huge", "https://example.com/h")
    s.full_content = huge
    block = retrieval.format_sources_for_prompt([s])
    # The whole formatted block must be roughly bounded by the cap plus
    # the header lines — definitely shorter than the raw huge input.
    check("formatted block shorter than raw content",
          len(block) < len(huge))
    # And shorter than cap + a generous header buffer.
    check("respects FULL_CONTENT_MAX_CHARS cap in output",
          len(block) < retrieval.FULL_CONTENT_MAX_CHARS + 500)


def test_retrieved_source_serialises_full_content():
    print("\n[types] RetrievedSource.to_dict includes full_content")
    s = _src(1, "A", "https://example.com/a")
    s.full_content = "extracted body"
    d = s.to_dict()
    check("full_content in dict", "full_content" in d)
    check("round-trip value", d["full_content"] == "extracted body")

    s_none = _src(2, "B", "https://example.com/b")
    dn = s_none.to_dict()
    check("defaults to None when not set", dn["full_content"] is None)


# ───── Source quality ─────

def test_authority_tiers():
    print("\n[source_quality] authority tiers")
    check(".gov domain scores high", _authority("usa.gov") >= 0.9)
    check("nature.com scores high", _authority("nature.com") >= 0.8)
    check("medium.com scores mid", 0.45 <= _authority("medium.com") <= 0.7)
    check("unknown domain is neutral", _authority("unknown-random-blog.com") == 0.5)
    check("top10 in name is low-quality", _authority("top10bestthings.com") <= 0.3)


def test_recency():
    print("\n[source_quality] recency")
    check("unknown date leans neutral-low", 0.3 <= _recency(None) <= 0.5)
    check("far future / today is ~1", _recency("2099-01-01") == 1.0)
    check("very old is near floor", _recency("2015-01-01") <= 0.15)
    check("malformed safe fallback", _recency("not-a-date") == 0.4)


def test_bias_risk():
    print("\n[source_quality] bias risk")
    clean = _bias_risk("https://example.com/x", "Research on X", "example.com")
    check("clean URL → 0", clean == 0.0)

    affiliate = _bias_risk(
        "https://shop.example.com/x?ref=affiliate&tag=x123",
        "Best X 2026",
        "shop.example.com",
    )
    check("affiliate URL → risk", affiliate > 0.4)

    listicle = _bias_risk("https://blog.example.com/x", "10 Best Widgets Ever", "blog.example.com")
    check("listicle title → risk", listicle > 0.0)


def test_score_sources_batch():
    print("\n[source_quality] score_sources batch")
    sources = [
        _src(1, "Nature: X found", "https://nature.com/x", "2025-10-01"),
        _src(2, "10 Best Widgets Ever", "https://top10widgets.com/?ref=aff", "2022-01-01"),
        _src(3, "Research on X", "https://www.sec.gov/press/x", "2026-02-01"),
    ]
    quality = score_sources(sources)
    check("one score per source", len(quality) == 3)
    check("nature has high overall", quality[1].overall >= 0.55, f"got {quality[1].overall}")
    check("sec.gov has highest overall", quality[3].overall >= quality[1].overall)
    check("top10 has low overall", quality[2].overall < quality[1].overall)


# ───── Confidence ─────

def test_confidence_bands_with_sources():
    print("\n[confidence] bands with sources")
    sources = [
        _src(1, "SEC filing", "https://sec.gov/x", "2026-02-01"),
        _src(2, "Nature article", "https://nature.com/x", "2026-01-10"),
        _src(3, "Federal Reserve report", "https://federalreserve.gov/x", "2025-12-20"),
    ]
    quality = score_sources(sources)
    consensus = {"agreement_score": 0.85, "contradictions": []}

    conf = compute_confidence(
        sources=sources,
        quality=quality,
        cited_source_ids={1, 2, 3},
        consensus=consensus,
        freshness_need="required",
    )
    check("band is high or moderate-high for strong set", conf.band in ("high", "moderate-high"),
          f"got {conf.band}")
    check("components present", set(conf.components.keys()) == {
        "source_quality", "evidence_quantity", "source_agreement",
        "freshness", "contradiction_penalty", "model_consensus",
    })


def test_confidence_no_sources_redistributes():
    print("\n[confidence] no sources → weights redistribute")
    conf = compute_confidence(
        sources=[],
        quality={},
        cited_source_ids=set(),
        consensus={"agreement_score": 0.2, "contradictions": [1, 2, 3]},
        freshness_need="required",
    )
    check("low band when models disagree and no sources", conf.band == "low", f"got {conf.band}")
    check("rationale mentions missing sources",
          "No external sources" in conf.rationale)


def test_confidence_contradiction_penalty():
    print("\n[confidence] contradiction penalty drops band")
    sources = [_src(1, "A", "https://example.com/a", "2026-03-01")]
    quality = score_sources(sources)
    strong_agreement = compute_confidence(
        sources=sources, quality=quality, cited_source_ids={1},
        consensus={"agreement_score": 0.9, "contradictions": []},
        freshness_need="helpful",
    )
    conflicted = compute_confidence(
        sources=sources, quality=quality, cited_source_ids={1},
        consensus={"agreement_score": 0.3, "contradictions": [1, 2, 3]},
        freshness_need="helpful",
    )
    # Band ordering: high > moderate-high > moderate > low
    order = {"low": 0, "moderate": 1, "moderate-high": 2, "high": 3}
    check("contradictions drop band",
          order[conflicted.band] < order[strong_agreement.band],
          f"{conflicted.band} vs {strong_agreement.band}")


# ───── Report schema ─────

VALID_REPORT_JSON = {
    "executive_summary": "Buy the MacBook Air M3 for the stated use.",
    "key_findings": [
        {"finding": "M3 has 18h battery life.", "citations": [1], "strength": "strong"},
        {"finding": "ThinkPad X1 is heavier by 300g.", "citations": [2], "strength": "moderate"},
        {"finding": "(model reasoning — unverified): likely to last 5 years", "citations": [], "strength": "weak"},
    ],
    "evidence_table": [
        {"claim": "M3 retail price is $1,299", "citations": [1], "strength": "strong", "note": "Apple store"},
    ],
    "source_confidence_note": "Primary sources on both laptops.",
    "contradictions": [
        {"point": "Keyboard quality debate",
         "side_a": "MBA keyboard preferred", "side_b": "TP keyboard preferred",
         "citations_a": [1], "citations_b": [2]}
    ],
    "risks_unknowns": ["Hardware revisions coming"],
    "recommendation": "MacBook Air M3, 16GB, 512GB.",
    "what_could_change": ["New ThinkPad release in Q3"],
    "next_actions": ["Order from Apple store", "Set up migration"],
}


def _dummy_confidence() -> ConfidenceScore:
    return ConfidenceScore(
        band="moderate-high",
        components={
            "source_quality": 0.7, "evidence_quantity": 0.8, "source_agreement": 0.6,
            "freshness": 0.9, "contradiction_penalty": 0.1, "model_consensus": 0.75,
        },
        rationale="Test rationale.",
    )


def test_report_parse_valid_json():
    print("\n[report_schema] valid JSON → StructuredReport")
    raw = json.dumps(VALID_REPORT_JSON)
    report, err = report_schema.parse_structured_report(
        raw=raw,
        confidence=_dummy_confidence(),
        valid_source_ids=[1, 2],
    )
    check("no error", err == "", err)
    check("report parsed", report is not None)
    check("3 key findings", len(report.key_findings) == 3)
    check("1 evidence row", len(report.evidence_table) == 1)
    check("2 next actions", len(report.next_actions) == 2)
    check("band preserved from passed confidence", report.confidence.band == "moderate-high")


def test_report_strips_invalid_citations():
    print("\n[report_schema] invented citations are stripped")
    bad = dict(VALID_REPORT_JSON)
    bad["key_findings"] = [
        {"finding": "A.", "citations": [1, 99, 2, 7], "strength": "strong"},
    ]
    report, _ = report_schema.parse_structured_report(
        raw=json.dumps(bad),
        confidence=_dummy_confidence(),
        valid_source_ids=[1, 2],
    )
    check("only valid ids survive", report.key_findings[0].citations == [1, 2],
          f"got {report.key_findings[0].citations}")


def test_report_parse_code_fence():
    print("\n[report_schema] JSON inside ```json fence")
    raw = "```json\n" + json.dumps(VALID_REPORT_JSON) + "\n```"
    report, err = report_schema.parse_structured_report(
        raw=raw,
        confidence=_dummy_confidence(),
        valid_source_ids=[1, 2],
    )
    check("fenced JSON parses", report is not None and err == "")


def test_report_text_fallback():
    print("\n[report_schema] text fallback when JSON parse fails")
    raw = "The decision is to buy the MacBook Air. Here is why..."
    report, err = report_schema.parse_structured_report(
        raw=raw,
        confidence=_dummy_confidence(),
        valid_source_ids=[1, 2],
    )
    check("returns None and error on non-JSON", report is None and err != "")

    wrapped = report_schema.text_fallback_report(raw, _dummy_confidence())
    check("fallback has recommendation set", wrapped.recommendation == raw)
    check("fallback has empty evidence_table", wrapped.evidence_table == [])


def test_collect_cited_source_ids():
    print("\n[report_schema] collect_cited_source_ids")
    report, _ = report_schema.parse_structured_report(
        raw=json.dumps(VALID_REPORT_JSON),
        confidence=_dummy_confidence(),
        valid_source_ids=[1, 2, 3],
    )
    ids = report_schema.collect_cited_source_ids(report)
    check("all cited ids collected", ids == {1, 2})


def test_schema_instruction_without_sources():
    print("\n[report_schema] schema instruction when no sources retrieved")
    instr = report_schema.build_schema_instruction([])
    check("instructs empty citations when no sources",
          "Leave every `citations` array empty" in instr)


def test_schema_instruction_with_sources():
    print("\n[report_schema] schema instruction with sources")
    instr = report_schema.build_schema_instruction([1, 2, 3])
    check("includes valid ids", "Valid citation IDs are: [1, 2, 3]" in instr)
    check("bans inventing citations", "forbidden" in instr.lower())


# ───── Scope extraction (upgrade #3) ─────

def test_scope_parse_happy_path():
    print("\n[scope] parse_scope happy path")
    sc = scope_mod.parse_scope({
        "timeframe": "Q4 2026",
        "region": "US",
        "audience": "solo founders",
        "decision_intent": "compare",
    })
    check("timeframe preserved", sc.timeframe == "Q4 2026")
    check("region preserved", sc.region == "US")
    check("audience preserved", sc.audience == "solo founders")
    check("intent normalised", sc.decision_intent == "compare")
    check("not empty", not sc.is_empty())


def test_scope_parse_placeholder_becomes_none():
    print("\n[scope] placeholder strings become None")
    sc = scope_mod.parse_scope({
        "timeframe": "null",
        "region": "N/A",
        "audience": "",
        "decision_intent": "unknown",
    })
    check("null string → None", sc.timeframe is None)
    check("N/A → None", sc.region is None)
    check("empty → None", sc.audience is None)
    check("unknown → None", sc.decision_intent is None)
    check("fully empty scope", sc.is_empty())


def test_scope_parse_invalid_input():
    print("\n[scope] parse_scope on non-dict input")
    check("None input → empty Scope", scope_mod.parse_scope(None).is_empty())
    check("string input → empty Scope", scope_mod.parse_scope("oops").is_empty())
    check("list input → empty Scope", scope_mod.parse_scope([]).is_empty())


def test_scope_intent_aliasing():
    print("\n[scope] decision_intent alias mapping")
    check("purchase → buy",
          scope_mod.parse_scope({"decision_intent": "purchase"}).decision_intent == "buy")
    check("develop → build",
          scope_mod.parse_scope({"decision_intent": "develop this"}).decision_intent == "build")
    check("vs → compare",
          scope_mod.parse_scope({"decision_intent": "vs"}).decision_intent == "compare")
    check("research → understand",
          scope_mod.parse_scope({"decision_intent": "research"}).decision_intent == "understand")
    check("strategy → plan",
          scope_mod.parse_scope({"decision_intent": "strategy"}).decision_intent == "plan")


def test_scope_intent_preserves_unknown_phrase():
    print("\n[scope] unknown intents keep their phrasing")
    sc = scope_mod.parse_scope({"decision_intent": "negotiate licensing"})
    check("preserves phrase", sc.decision_intent == "negotiate licensing")


def test_scope_cleanstr_trims_and_caps():
    print("\n[scope] _clean_str trims and caps length")
    long_val = "x" * 500
    sc = scope_mod.parse_scope({"audience": "  spaced  out  "})
    check("whitespace collapsed", sc.audience == "spaced out")
    sc2 = scope_mod.parse_scope({"audience": long_val})
    check("length capped", sc2.audience is not None and len(sc2.audience) <= 160)


def test_format_scope_for_prompt():
    print("\n[scope] format_scope_for_prompt")
    sc = scope_mod.parse_scope({
        "timeframe": "Q4 2026",
        "region": "US",
        "audience": "solo founders",
        "decision_intent": "compare",
    })
    block = scope_mod.format_scope_for_prompt(sc)
    check("header present", block.startswith("## Scope"))
    check("audience line", "Audience: solo founders" in block)
    check("intent line", "Intent:" in block and "compare" in block)
    check("when line", "When:" in block and "Q4 2026" in block)
    check("where line", "Where:" in block and "US" in block)

    empty = scope_mod.format_scope_for_prompt(Scope())
    check("empty scope → empty string", empty == "")


def test_augment_query_with_scope_adds_region():
    print("\n[scope] augment_query_with_scope adds region")
    sc = Scope(region="UK only")
    q = scope_mod.augment_query_with_scope("best coding assistants", sc)
    check("region appended", "UK only" in q)


def test_augment_query_with_scope_skips_global():
    print("\n[scope] augment_query_with_scope skips 'global'")
    sc = Scope(region="global")
    q = scope_mod.augment_query_with_scope("best coding assistants", sc)
    check("global not appended", "global" not in q.lower())


def test_augment_query_skips_redundant_year():
    print("\n[scope] augment_query skips timeframe when query already has year")
    sc = Scope(timeframe="2024")
    q = scope_mod.augment_query_with_scope("best laptops 2026 review", sc)
    check("existing 2026 kept, 2024 not injected", "2024" not in q)
    check("query preserved", "best laptops 2026 review" in q)


def test_augment_query_extracts_year_from_timeframe():
    print("\n[scope] augment_query extracts year when timeframe has one")
    sc = Scope(timeframe="Q4 2026 earnings")
    q = scope_mod.augment_query_with_scope("acme inc revenue", sc)
    check("year injected", "2026" in q)


def test_augment_query_noop_when_empty_scope():
    print("\n[scope] augment_query is a no-op when scope is empty")
    q = scope_mod.augment_query_with_scope("test query", Scope())
    check("unchanged", q == "test query")


def test_scope_to_dict_round_trip():
    print("\n[scope] Scope.to_dict round-trip")
    sc = Scope(
        timeframe="current", region="EU",
        audience="CFOs", decision_intent="validate",
    )
    d = sc.to_dict()
    check("keys present", set(d.keys()) == {"timeframe", "region", "audience", "decision_intent"})
    check("values round-trip", d["audience"] == "CFOs" and d["decision_intent"] == "validate")


def test_plan_queries_uses_scope():
    print("\n[retrieval] _plan_queries honours scope")
    sc = Scope(region="EU", timeframe="2026")
    queries = retrieval._plan_queries(
        refined_prompt="compare CRMs for B2B SaaS",
        phase_prompt="Compare top 5 CRMs on pricing and feature depth.",
        category="comparison_evaluation",
        scope=sc,
    )
    # First query is the phase prompt verbatim (no augmentation).
    check("first query still phase prompt", queries[0].startswith("Compare"))
    # Secondary query should have been scope-augmented (EU appended).
    joined = " ".join(queries[1:])
    check("region threaded into secondary query", "EU" in joined)


# ───── Multi-provider retrieval (upgrade #4) ─────

def _fake_raw(provider: str, url: str, title: str = "Hit", content: str = "a snippet",
              full: str | None = None, published: str | None = None, relevance: float = 0.7,
              query: str = "q") -> "retrievers_base.RawResult":
    return retrievers_base.RawResult(
        provider=provider, title=title, url=url, snippet=content,
        full_content=full, relevance=relevance, published=published, query=query,
    )


def test_provider_is_configured_respects_env():
    print("\n[retrievers] is_configured() follows env keys")
    saved = (os.environ.get("TAVILY_API_KEY"), os.environ.get("BRAVE_SEARCH_API_KEY"))
    try:
        os.environ.pop("TAVILY_API_KEY", None)
        os.environ.pop("BRAVE_SEARCH_API_KEY", None)
        check("no keys → tavily False", not tavily_provider.is_configured())
        check("no keys → brave False", not brave_provider.is_configured())
        check("no keys → orchestrator False", not retrieval.is_configured())
        check("list_configured_providers empty", list_configured_providers() == [])

        os.environ["TAVILY_API_KEY"] = "x"
        check("tavily set → tavily True", tavily_provider.is_configured())
        check("orchestrator True when any set", retrieval.is_configured())
        check("list shows tavily only", list_configured_providers() == ["tavily"])

        os.environ["BRAVE_SEARCH_API_KEY"] = "y"
        check("list shows both", set(list_configured_providers()) == {"tavily", "brave"})
    finally:
        for k, v in zip(("TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY"), saved):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_brave_isoify_page_age():
    print("\n[retrievers.brave] _isoify_page_age")
    check("date passes through",
          brave_provider._isoify_page_age("2026-04-12") == "2026-04-12")
    check("ISO with time extracted",
          brave_provider._isoify_page_age("2026-04-12T08:00:00Z") == "2026-04-12T08:00:00")
    check("humanised rejected",
          brave_provider._isoify_page_age("6 days ago") is None)
    check("None safe", brave_provider._isoify_page_age(None) is None)
    check("empty safe", brave_provider._isoify_page_age("") is None)


def test_rrf_boosts_agreement():
    print("\n[retrieval] RRF fuses providers and boosts corroborated URLs")
    shared = _fake_raw("tavily", "https://example.com/A", title="A", full="body-A")
    shared_b = _fake_raw("brave",  "https://example.com/A", title="A")
    tav_only = _fake_raw("tavily", "https://example.com/B", title="B")
    brv_only = _fake_raw("brave",  "https://example.com/C", title="C")

    fused = retrieval._rrf_fuse({
        "tavily": [shared,   tav_only],
        "brave":  [shared_b, brv_only],
    })
    # URL -> rrf_score and providers_agreeing
    by_url = {rep.url: (score, agreeing) for score, rep, agreeing in fused}

    check("shared URL ranks highest",
          fused[0][1].url == "https://example.com/A",
          f"got order {[r[1].url for r in fused]}")
    check("shared URL has both providers",
          set(by_url["https://example.com/A"][1]) == {"tavily", "brave"})
    check("single-provider URL has one provider",
          by_url["https://example.com/B"][1] == ["tavily"])
    check("full_content preserved on merge",
          fused[0][1].full_content == "body-A")


def test_rrf_single_provider_still_works():
    print("\n[retrieval] RRF handles a single-provider map")
    a = _fake_raw("tavily", "https://example.com/A", title="A")
    b = _fake_raw("tavily", "https://example.com/B", title="B")
    fused = retrieval._rrf_fuse({"tavily": [a, b]})
    check("two results returned", len(fused) == 2)
    check("first beats second", fused[0][0] > fused[1][0])
    check("each has one provider",
          all(len(agreeing) == 1 for _, _, agreeing in fused))


async def _fake_tavily(query: str, max_results: int = 6) -> list["retrievers_base.RawResult"]:
    return [
        _fake_raw("tavily", "https://nature.com/shared", title="Shared (Tavily rank 0)",
                  full="article body from nature", published="2025-11-03", relevance=0.9, query=query),
        _fake_raw("tavily", "https://tav.only/x", title="Tav-only",
                  full="tav body", relevance=0.7, query=query),
    ]


async def _fake_brave(query: str, max_results: int = 6) -> list["retrievers_base.RawResult"]:
    return [
        _fake_raw("brave", "https://nature.com/shared", title="Shared (Brave rank 0)",
                  full=None, published="2025-11-03", relevance=0.95, query=query),
        _fake_raw("brave", "https://brv.only/y", title="Brv-only",
                  full=None, relevance=0.8, query=query),
    ]


async def _fake_fail(query: str, max_results: int = 6) -> list:
    raise RuntimeError("boom")


def test_retrieve_sources_end_to_end_fused():
    print("\n[retrieval] retrieve_sources fuses configured providers")
    saved = (os.environ.get("TAVILY_API_KEY"), os.environ.get("BRAVE_SEARCH_API_KEY"))
    tav_real = tavily_provider.search
    brv_real = brave_provider.search
    try:
        os.environ["TAVILY_API_KEY"] = "x"
        os.environ["BRAVE_SEARCH_API_KEY"] = "y"
        tavily_provider.search = _fake_tavily
        brave_provider.search = _fake_brave

        sources, meta = asyncio.run(retrieval.retrieve_sources(
            refined_prompt="Research X",
            phase_prompt="Research X in depth.",
            category="deep_research",
            max_sources=10,
        ))

        urls = [s.url for s in sources]
        check("all three unique URLs present",
              set(urls) == {"https://nature.com/shared", "https://tav.only/x", "https://brv.only/y"})
        # Shared URL should rank first (appears in both providers).
        check("shared URL ranked first", sources[0].url == "https://nature.com/shared")
        shared_src = sources[0]
        check("shared source has both providers",
              set(shared_src.providers_agreeing) == {"tavily", "brave"})
        check("shared source keeps Tavily's full_content",
              shared_src.full_content == "article body from nature")

        check("meta lists both providers as used",
              set(meta["providers_used"]) == {"tavily", "brave"})
        check("meta provider label is joined",
              meta["provider"] in ("brave+tavily", "tavily+brave"))
        check("meta counts per-provider hits",
              meta["per_provider_counts"].get("tavily", 0) >= 2 and
              meta["per_provider_counts"].get("brave", 0) >= 2)
        # Shared source + tav_only both carry full_content (from Tavily).
        # Brave-only URL has none.
        check("meta counts enriched sources",
              meta["enriched"] == 2,
              f"got {meta['enriched']}")
    finally:
        tavily_provider.search = tav_real
        brave_provider.search = brv_real
        for k, v in zip(("TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY"), saved):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_retrieve_sources_tolerates_provider_failure():
    print("\n[retrieval] one provider failing doesn't kill the batch")
    saved = (os.environ.get("TAVILY_API_KEY"), os.environ.get("BRAVE_SEARCH_API_KEY"))
    tav_real = tavily_provider.search
    brv_real = brave_provider.search
    try:
        os.environ["TAVILY_API_KEY"] = "x"
        os.environ["BRAVE_SEARCH_API_KEY"] = "y"
        tavily_provider.search = _fake_tavily
        brave_provider.search = _fake_fail   # raises

        sources, meta = asyncio.run(retrieval.retrieve_sources(
            refined_prompt="Research X",
            phase_prompt="Research X in depth.",
            category="deep_research",
            max_sources=5,
        ))
        urls = {s.url for s in sources}
        check("sources still returned", len(sources) > 0)
        check("only Tavily URLs present", urls == {"https://nature.com/shared", "https://tav.only/x"})
        check("providers_returning lists only tavily",
              meta["providers_returning"] == ["tavily"])
    finally:
        tavily_provider.search = tav_real
        brave_provider.search = brv_real
        for k, v in zip(("TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY"), saved):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_retrieve_sources_no_providers_configured():
    print("\n[retrieval] no providers configured → empty")
    saved = (os.environ.get("TAVILY_API_KEY"), os.environ.get("BRAVE_SEARCH_API_KEY"))
    try:
        os.environ.pop("TAVILY_API_KEY", None)
        os.environ.pop("BRAVE_SEARCH_API_KEY", None)
        sources, meta = asyncio.run(retrieval.retrieve_sources(
            refined_prompt="Q", phase_prompt="Q", category="deep_research",
        ))
        check("empty sources", sources == [])
        check("configured=False", meta.get("configured") is False)
        check("provider label is 'none'", meta.get("provider") == "none")
    finally:
        for k, v in zip(("TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY"), saved):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_retrieve_sources_invokes_progress_and_source_callbacks():
    print("\n[retrieval] retrieve_sources invokes on_progress + on_source_added")
    saved = (os.environ.get("TAVILY_API_KEY"), os.environ.get("BRAVE_SEARCH_API_KEY"))
    tav_real = tavily_provider.search
    brv_real = brave_provider.search
    try:
        os.environ["TAVILY_API_KEY"] = "x"
        os.environ["BRAVE_SEARCH_API_KEY"] = "y"
        tavily_provider.search = _fake_tavily
        brave_provider.search = _fake_brave

        progress_events = []
        added_sources = []

        async def on_progress(info):
            progress_events.append(info)

        async def on_source_added(src_dict):
            added_sources.append(src_dict)

        sources, _meta = asyncio.run(retrieval.retrieve_sources(
            refined_prompt="q", phase_prompt="q",
            category="deep_research",
            max_sources=5,
            on_progress=on_progress,
            on_source_added=on_source_added,
        ))

        stages = [e.get("stage") for e in progress_events]
        check("querying stage emitted", "querying" in stages)
        check("returned stage emitted", "returned" in stages)
        check("fusing stage emitted", "fusing" in stages)

        # Per-provider querying events (one per provider per query).
        querying = [e for e in progress_events if e.get("stage") == "querying"]
        providers = {e.get("provider") for e in querying}
        check("both providers appear in querying", providers == {"tavily", "brave"})

        # on_source_added fires once per final source.
        check("source_added called per final source",
              len(added_sources) == len(sources),
              f"added={len(added_sources)} sources={len(sources)}")
        check("first added has provider field",
              added_sources and "provider" in added_sources[0])
    finally:
        tavily_provider.search = tav_real
        brave_provider.search = brv_real
        for k, v in zip(("TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY"), saved):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_retrieve_sources_swallows_callback_exceptions():
    print("\n[retrieval] retrieve_sources tolerates raising callbacks")
    saved = (os.environ.get("TAVILY_API_KEY"), os.environ.get("BRAVE_SEARCH_API_KEY"))
    tav_real = tavily_provider.search
    try:
        os.environ["TAVILY_API_KEY"] = "x"
        os.environ.pop("BRAVE_SEARCH_API_KEY", None)
        tavily_provider.search = _fake_tavily

        async def bad_progress(info):
            raise RuntimeError("callback boom")

        async def bad_source(src):
            raise RuntimeError("source callback boom")

        sources, meta = asyncio.run(retrieval.retrieve_sources(
            refined_prompt="q", phase_prompt="q", category="deep_research",
            max_sources=5,
            on_progress=bad_progress,
            on_source_added=bad_source,
        ))
        check("sources still returned despite raising callbacks", len(sources) > 0)
        check("meta still populated", meta.get("configured") is True)
    finally:
        tavily_provider.search = tav_real
        for k, v in zip(("TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY"), saved):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_retrieved_source_carries_provider_fields():
    print("\n[types] RetrievedSource exposes provider + providers_agreeing")
    s = RetrievedSource(
        id=1, title="T", url="https://x", domain="x",
        published=None, snippet="", retrieved_at="t",
        provider="brave", providers_agreeing=["brave", "tavily"],
    )
    d = s.to_dict()
    check("provider key present", d["provider"] == "brave")
    check("providers_agreeing key present",
          d["providers_agreeing"] == ["brave", "tavily"])


# ───── Per-claim verification (upgrade #6) ─────

from synthesis.orchestrator import verification as verification_mod
from synthesis.orchestrator.types import EvidenceRow, StructuredReport


def _make_report_for_verification() -> "StructuredReport":
    return StructuredReport(
        executive_summary="x",
        key_findings=[],
        evidence_table=[
            EvidenceRow(claim="The sky is blue.", citations=[1], strength="strong"),
            EvidenceRow(claim="Rocket fuel is orange juice.",
                        citations=[2], strength="moderate"),
            EvidenceRow(claim="Uncited claim.", citations=[], strength="weak"),
        ],
        source_confidence_note="",
        contradictions=[],
        risks_unknowns=[],
        recommendation="",
        what_could_change=[],
        next_actions=[],
        confidence=ConfidenceScore(band="moderate",
                                    components={"source_quality": 0.5},
                                    rationale=""),
    )


def _make_sources_for_verification() -> list["RetrievedSource"]:
    return [
        _src(1, "Sky colour study", "https://x.gov/sky"),
        _src(2, "Chemistry primer", "https://x.edu/chem"),
    ]


def test_parse_verdict_accepts_valid_variants():
    print("\n[verification] _parse_verdict accepts known verdicts")
    check("supported parses",
          verification_mod._parse_verdict('{"verdict":"supported","reason":"ok"}') == "supported")
    check("partial parses",
          verification_mod._parse_verdict('{"verdict":"partial","reason":"ok"}') == "partial")
    check("unsupported parses",
          verification_mod._parse_verdict('{"verdict":"UNSUPPORTED","reason":"ok"}') == "unsupported")
    check("unknown rejected",
          verification_mod._parse_verdict('{"verdict":"yes","reason":"ok"}') == "")
    check("malformed rejected",
          verification_mod._parse_verdict("no json here") == "")


def test_verify_skips_rows_without_citations():
    print("\n[verification] rows without citations get None verdict")
    async def call_should_not_run(prompt, system):
        raise AssertionError("should not be called for uncited rows")
    report = _make_report_for_verification()
    # Zero sources → skip entirely (early exit).
    stats = asyncio.run(verification_mod.verify_evidence_rows(
        report=report, sources=[], call_fn=call_should_not_run,
    ))
    check("verified=0 when no sources", stats["verified"] == 0)


def test_verify_writes_verdicts_to_rows():
    print("\n[verification] verdicts populate EvidenceRow.verification")
    calls = {"n": 0}

    async def mock_call(prompt, system):
        calls["n"] += 1
        # Alternate supported / unsupported based on call count.
        verdict = "supported" if calls["n"] % 2 == 1 else "unsupported"
        return (f'{{"verdict":"{verdict}","reason":"ok"}}', "mock")

    report = _make_report_for_verification()
    sources = _make_sources_for_verification()
    stats = asyncio.run(verification_mod.verify_evidence_rows(
        report=report, sources=sources, call_fn=mock_call,
    ))

    # Only the two CITED rows are verified; the uncited row stays None.
    check("two rows verified", stats["verified"] == 2, f"got {stats}")
    check("first row supported", report.evidence_table[0].verification == "supported")
    check("second row unsupported", report.evidence_table[1].verification == "unsupported")
    check("uncited row stays None", report.evidence_table[2].verification is None)
    check("stats counts supported=1", stats["supported"] == 1)
    check("stats counts unsupported=1", stats["unsupported"] == 1)


def test_verify_gracefully_handles_model_failure():
    print("\n[verification] individual model failure leaves row verification=None")
    async def failing_call(prompt, system):
        raise RuntimeError("mock model timeout")
    report = _make_report_for_verification()
    sources = _make_sources_for_verification()
    stats = asyncio.run(verification_mod.verify_evidence_rows(
        report=report, sources=sources, call_fn=failing_call,
    ))
    check("verified=0 when all calls fail", stats["verified"] == 0)
    check("row verifications remain None",
          all(r.verification is None for r in report.evidence_table))


def test_verify_respects_max_claims():
    print("\n[verification] respects max_claims cap")
    # Build a report with 10 cited rows; cap at 3.
    rows = [
        EvidenceRow(claim=f"Claim {i}.", citations=[1], strength="moderate")
        for i in range(10)
    ]
    report = StructuredReport(
        executive_summary="x", key_findings=[], evidence_table=rows,
        source_confidence_note="", contradictions=[], risks_unknowns=[],
        recommendation="", what_could_change=[], next_actions=[],
        confidence=ConfidenceScore(band="moderate", components={}, rationale=""),
    )
    calls = {"n": 0}

    async def counting_call(prompt, system):
        calls["n"] += 1
        return ('{"verdict":"supported","reason":"ok"}', "mock")

    stats = asyncio.run(verification_mod.verify_evidence_rows(
        report=report, sources=_make_sources_for_verification(),
        call_fn=counting_call, max_claims=3,
    ))
    check("exactly 3 calls made", calls["n"] == 3, f"got {calls['n']}")
    check("first 3 rows verified",
          all(r.verification == "supported" for r in rows[:3]))
    check("remaining rows untouched",
          all(r.verification is None for r in rows[3:]))


def test_evidence_row_serialises_verification():
    print("\n[types] EvidenceRow.verification round-trips via to_dict")
    r = EvidenceRow(claim="c", citations=[1], strength="strong")
    r.verification = "partial"
    from dataclasses import asdict
    d = asdict(r)
    check("verification in dict", d["verification"] == "partial")


# ───── Runner ─────

def main():
    tests = [
        test_retrieval_graceful_fallback,
        test_domain_extraction,
        test_query_planning,
        test_sources_prompt_format,
        test_clean_raw_content_hygiene,
        test_clean_raw_content_truncation,
        test_format_uses_full_content_when_present,
        test_format_truncates_full_content_to_limit,
        test_retrieved_source_serialises_full_content,
        test_authority_tiers,
        test_recency,
        test_bias_risk,
        test_score_sources_batch,
        test_confidence_bands_with_sources,
        test_confidence_no_sources_redistributes,
        test_confidence_contradiction_penalty,
        test_report_parse_valid_json,
        test_report_strips_invalid_citations,
        test_report_parse_code_fence,
        test_report_text_fallback,
        test_collect_cited_source_ids,
        test_schema_instruction_without_sources,
        test_schema_instruction_with_sources,
        test_scope_parse_happy_path,
        test_scope_parse_placeholder_becomes_none,
        test_scope_parse_invalid_input,
        test_scope_intent_aliasing,
        test_scope_intent_preserves_unknown_phrase,
        test_scope_cleanstr_trims_and_caps,
        test_format_scope_for_prompt,
        test_augment_query_with_scope_adds_region,
        test_augment_query_with_scope_skips_global,
        test_augment_query_skips_redundant_year,
        test_augment_query_extracts_year_from_timeframe,
        test_augment_query_noop_when_empty_scope,
        test_scope_to_dict_round_trip,
        test_plan_queries_uses_scope,
        test_provider_is_configured_respects_env,
        test_brave_isoify_page_age,
        test_rrf_boosts_agreement,
        test_rrf_single_provider_still_works,
        test_retrieve_sources_end_to_end_fused,
        test_retrieve_sources_tolerates_provider_failure,
        test_retrieve_sources_no_providers_configured,
        test_retrieve_sources_invokes_progress_and_source_callbacks,
        test_retrieve_sources_swallows_callback_exceptions,
        test_retrieved_source_carries_provider_fields,
        test_parse_verdict_accepts_valid_variants,
        test_verify_skips_rows_without_citations,
        test_verify_writes_verdicts_to_rows,
        test_verify_gracefully_handles_model_failure,
        test_verify_respects_max_claims,
        test_evidence_row_serialises_verification,
    ]
    for t in tests:
        t()

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    print(f"\n{'-' * 60}")
    print(f"Synthesis research tests: {passed}/{total} passed")
    if passed != total:
        failures = [n for n, ok, _ in checks if not ok]
        print(f"FAILED: {failures}")
        sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
