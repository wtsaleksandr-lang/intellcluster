"""
Golden prompt set.

20 curated prompts covering every Synthesis category + a mix of
freshness needs, scope signals, and complexity.

`expectations` lets each judge know what to check against:

  needs_freshness         — freshness detector should return "required" or "helpful"
  expected_scope_fields   — which Scope fields PE should be able to fill in
  min_expected_sources    — when retrieval runs, at least this many sources
  allow_empty_sources     — True if we tolerate zero sources (pure-reasoning prompts)
  max_band_without_sources— safety ceiling when sources are empty
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GoldenPrompt:
    id: str
    category: str
    mode: str
    prompt: str
    expectations: dict[str, Any] = field(default_factory=dict)


GOLDEN_PROMPTS: list[GoldenPrompt] = [
    # ───── deep_research (2) ─────
    GoldenPrompt(
        id="p01-deep-ai-reg",
        category="deep_research",
        mode="standard",
        prompt="Summarize the most significant AI regulation developments in 2026 across the US, EU, and UK.",
        expectations={
            "needs_freshness": True,
            "expected_scope_fields": ["timeframe", "region"],
            "min_expected_sources": 3,
            "max_band_without_sources": "moderate",
        },
    ),
    GoldenPrompt(
        id="p02-deep-synbio",
        category="deep_research",
        mode="standard",
        prompt="What are the emerging risk categories in synthetic biology that regulators are currently concerned about?",
        expectations={
            "needs_freshness": True,
            "expected_scope_fields": ["timeframe"],
            "min_expected_sources": 3,
        },
    ),

    # ───── competitor_market_research (2) ─────
    GoldenPrompt(
        id="p03-comp-crm",
        category="competitor_market_research",
        mode="standard",
        prompt="Compare the top 5 CRM SaaS vendors for a B2B SaaS company (<50 employees) on pricing, integrations, and churn-prevention features.",
        expectations={
            "needs_freshness": True,
            "expected_scope_fields": ["audience", "decision_intent"],
            "min_expected_sources": 4,
        },
    ),
    GoldenPrompt(
        id="p04-comp-vercel",
        category="competitor_market_research",
        mode="standard",
        prompt="Who are the main competitors to Vercel in the frontend-deploy space, and where is Vercel strongest vs weakest today?",
        expectations={
            "needs_freshness": True,
            "min_expected_sources": 4,
        },
    ),

    # ───── business_ideas_validation (2) ─────
    GoldenPrompt(
        id="p05-idea-tradies",
        category="business_ideas_validation",
        mode="standard",
        prompt="Is a local marketplace for tradespeople (plumbers, electricians, roofers) viable in the UK in 2026? Analyze demand, competition, unit economics.",
        expectations={
            "needs_freshness": True,
            "expected_scope_fields": ["region", "decision_intent"],
            "min_expected_sources": 3,
        },
    ),
    GoldenPrompt(
        id="p06-idea-restaurant",
        category="business_ideas_validation",
        mode="standard",
        prompt="Should an indie founder build a SaaS for restaurant inventory management in 2026? Validate demand, incumbents, pricing reality.",
        expectations={
            "needs_freshness": True,
            "expected_scope_fields": ["audience", "decision_intent"],
            "min_expected_sources": 3,
        },
    ),

    # ───── marketing_growth (2) ─────
    GoldenPrompt(
        id="p07-mkt-lawyers",
        category="marketing_growth",
        mode="standard",
        prompt="Best acquisition channels in 2026 for a B2B SaaS targeting solo lawyers in the US.",
        expectations={
            "needs_freshness": True,
            "expected_scope_fields": ["audience", "region", "timeframe"],
            "min_expected_sources": 3,
        },
    ),
    GoldenPrompt(
        id="p08-mkt-first100",
        category="marketing_growth",
        mode="standard",
        prompt="How to get the first 100 paying users for a developer tool (API testing, open-source adjacent)?",
        expectations={
            "needs_freshness": True,
            "expected_scope_fields": ["audience", "decision_intent"],
            "min_expected_sources": 3,
        },
    ),

    # ───── product_offer_design (2) ─────
    GoldenPrompt(
        id="p09-offer-ai-coding",
        category="product_offer_design",
        mode="standard",
        prompt="Pricing benchmark for AI coding assistants in 2026 — what tiers, price points, and add-ons do leading products use?",
        expectations={
            "needs_freshness": True,
            "expected_scope_fields": ["timeframe"],
            "min_expected_sources": 3,
        },
    ),
    GoldenPrompt(
        id="p10-offer-3tier",
        category="product_offer_design",
        mode="standard",
        prompt="How should I structure a 3-tier pricing page for a SaaS DAU-analytics tool? Include anchor pricing, upgrade levers, and copy structure.",
        expectations={
            "needs_freshness": True,
            "expected_scope_fields": ["decision_intent"],
        },
    ),

    # ───── funnel_conversion (2) ─────
    GoldenPrompt(
        id="p11-funnel-checkout",
        category="funnel_conversion",
        mode="standard",
        prompt="Improve checkout conversion for a Shopify e-commerce store selling premium outdoor gear ($80-400 AOV).",
        expectations={
            "needs_freshness": True,
            "expected_scope_fields": ["decision_intent"],
        },
    ),
    GoldenPrompt(
        id="p12-funnel-trial",
        category="funnel_conversion",
        mode="standard",
        prompt="Optimize a free-trial signup landing page for a B2B SaaS. What sections, order, and copy patterns convert best in 2026?",
        expectations={
            "needs_freshness": True,
            "expected_scope_fields": ["timeframe"],
        },
    ),

    # ───── comparison_evaluation (2) ─────
    GoldenPrompt(
        id="p13-compare-coding",
        category="comparison_evaluation",
        mode="standard",
        prompt="Claude Code vs Cursor vs GitHub Copilot — which is best for a 10-person TypeScript + Python team in 2026?",
        expectations={
            "needs_freshness": True,
            "expected_scope_fields": ["audience", "timeframe", "decision_intent"],
            "min_expected_sources": 4,
        },
    ),
    GoldenPrompt(
        id="p14-compare-db",
        category="comparison_evaluation",
        mode="standard",
        prompt="Postgres vs MongoDB for a new social-media app with an expected 10M users and heavy write traffic.",
        expectations={
            "needs_freshness": True,
            "expected_scope_fields": ["decision_intent"],
            "min_expected_sources": 3,
        },
    ),

    # ───── ai_systems_automation (2) ─────
    GoldenPrompt(
        id="p15-ai-rag-legal",
        category="ai_systems_automation",
        mode="standard",
        prompt="Architecture for a RAG chatbot over 100k legal documents — model choice, retrieval, guardrails, cost per query in 2026.",
        expectations={
            "needs_freshness": True,
            "expected_scope_fields": ["timeframe"],
            "min_expected_sources": 3,
        },
    ),
    GoldenPrompt(
        id="p16-ai-support",
        category="ai_systems_automation",
        mode="standard",
        prompt="Design an AI automation to triage inbound customer support tickets for a 50-person SaaS. Include tool stack and cost estimate.",
        expectations={
            "needs_freshness": True,
            "expected_scope_fields": ["audience"],
        },
    ),

    # ───── decision_strategy (2) ─────
    GoldenPrompt(
        id="p17-strat-raise",
        category="decision_strategy",
        mode="standard",
        prompt="A profitable $400k-ARR bootstrapped SaaS: should they raise a seed round in 2026 or stay bootstrapped? Analyze the tradeoffs.",
        expectations={
            "needs_freshness": True,
            "expected_scope_fields": ["audience", "decision_intent", "timeframe"],
        },
    ),
    GoldenPrompt(
        id="p18-strat-build-buy",
        category="decision_strategy",
        mode="standard",
        prompt="For a 200-person B2B SaaS, buy vs build for internal analytics tooling? Analyze opportunity cost and realistic timelines.",
        expectations={
            "needs_freshness": True,
            "expected_scope_fields": ["audience", "decision_intent"],
        },
    ),

    # ───── Edge cases (2) ─────
    GoldenPrompt(
        id="p19-cap-theorem",
        category="deep_research",
        mode="standard",
        # Pure-concept prompt: should still retrieve but sources are less critical.
        prompt="Explain the CAP theorem and its practical implications for choosing distributed databases.",
        expectations={
            "needs_freshness": False,
            "allow_empty_sources": True,
            "max_band_without_sources": "moderate-high",
        },
    ),
    GoldenPrompt(
        id="p20-scope-uk-seo",
        category="marketing_growth",
        mode="standard",
        # Scope extraction test: explicit region + timeframe in the prompt.
        prompt="Best SEO tools for UK ecommerce stores in 2026 — compare on price and feature depth.",
        expectations={
            "needs_freshness": True,
            "expected_scope_fields": ["region", "timeframe", "decision_intent"],
            "min_expected_sources": 3,
        },
    ),
]


QUICK_PROMPT_IDS = {"p01-deep-ai-reg", "p13-compare-coding", "p20-scope-uk-seo"}


def get_prompts(quick: bool = False) -> list[GoldenPrompt]:
    if quick:
        return [p for p in GOLDEN_PROMPTS if p.id in QUICK_PROMPT_IDS]
    return list(GOLDEN_PROMPTS)
