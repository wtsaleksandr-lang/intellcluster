"""
Mock Provider for Test Mode.
Returns deterministic, realistic-looking outputs without calling any real API.
Simulates latency, failures, and timeouts for testing.
"""

import asyncio
import json
import random
import time

from .base import BaseProvider, ModelResult

# Deterministic mock outputs per model, keyed by model name
_MOCK_OUTPUTS = {
    "gpt-4o": {
        "research": (
            "## Analysis (GPT-4o)\n\n"
            "Based on comprehensive analysis, the key findings are:\n\n"
            "1. **Market positioning**: The primary opportunity lies in differentiation through multi-model synthesis. "
            "No current competitor offers transparent multi-AI comparison.\n\n"
            "2. **Pricing strategy**: Freemium with usage-based tiers is optimal. "
            "Target $29/mo for professionals, $99/mo for teams.\n\n"
            "3. **Distribution**: SEO + community-driven growth. "
            "Build public comparison pages that rank for 'AI comparison' queries.\n\n"
            "4. **Key risk**: API cost management at scale. "
            "Implement intelligent caching and tier-based model selection."
        ),
        "latency_range": (3000, 8000),
    },
    "gpt-4o-mini": {
        "research": (
            "## Analysis (GPT-4o-mini)\n\n"
            "Key points:\n\n"
            "1. Focus on SEO and organic traffic for sustainable growth\n"
            "2. Use freemium model to drive adoption\n"
            "3. Target small business owners who need AI but can't evaluate models\n"
            "4. Content marketing around AI comparisons will drive qualified traffic"
        ),
        "latency_range": (1500, 4000),
    },
    "claude-sonnet-4-6": {
        "research": (
            "## Analysis (Claude Sonnet)\n\n"
            "I've examined this from multiple angles:\n\n"
            "**Strategic Positioning:**\n"
            "The multi-AI approach addresses a genuine market gap. Most users don't know which AI "
            "gives better answers for their specific domain. This product solves that by abstracting "
            "the model selection entirely.\n\n"
            "**Growth Strategy:**\n"
            "- Phase 1: Build authority through transparent AI comparison content\n"
            "- Phase 2: Launch affiliate program with AI education creators\n"
            "- Phase 3: Enterprise API for businesses needing multi-model validation\n\n"
            "**Unique Insight:**\n"
            "The 'proof mechanism' (showing why the combined answer is better) is your key differentiator. "
            "No competitor explains their reasoning process."
        ),
        "latency_range": (5000, 15000),
    },
    "claude-opus-4-6": {
        "research": (
            "## Deep Analysis (Claude Opus)\n\n"
            "After thorough examination of the strategic landscape:\n\n"
            "1. **Core Value Proposition**: Multi-model orchestration provides verifiable quality improvement. "
            "Testing shows 23-40% higher accuracy on complex queries vs single-model approaches.\n\n"
            "2. **Market Timing**: The AI tool market is fragmenting. Users are overwhelmed by choices. "
            "An aggregator/orchestrator positioned as 'the answer, not a model' captures latent demand.\n\n"
            "3. **Moat Building**: The synthesis layer (strategist + decision maker) represents proprietary IP "
            "that improves with usage data. This creates a defensible advantage over time."
        ),
        "latency_range": (8000, 20000),
    },
    "gemini-2.5-flash": {
        "research": (
            "## Analysis (Gemini)\n\n"
            "Here's my assessment:\n\n"
            "1. **SEO Opportunity**: 'Best AI model for [task]' queries have high intent and growing volume. "
            "Create programmatic pages comparing AI outputs for specific use cases.\n\n"
            "2. **Pricing**: Align with market — $19-49/mo for individuals, $149/mo for teams. "
            "Offer 3 free runs to demonstrate value.\n\n"
            "3. **Technical Moat**: The multi-phase research with context propagation creates genuinely "
            "better outputs. Document and showcase this with before/after comparisons.\n\n"
            "4. **Partnership**: Reach out to AI newsletter writers for early coverage."
        ),
        "latency_range": (2000, 6000),
    },
    "deepseek-chat": {
        "research": (
            "## Analysis (DeepSeek)\n\n"
            "Key strategic recommendations:\n\n"
            "1. Cost efficiency is critical — use tiered model pools to maintain margins\n"
            "2. Target B2B first: consultants, agencies, researchers who make decisions daily\n"
            "3. Build API access for developers who want multi-model in their own products\n"
            "4. Create a 'quality score' metric that quantifies the multi-model advantage"
        ),
        "latency_range": (4000, 12000),
    },
    "grok-3": {
        "research": (
            "## Analysis (Grok)\n\n"
            "Straight to the point:\n\n"
            "1. **Go-to-market**: Launch on Product Hunt + Hacker News simultaneously. "
            "The 'multiple AIs arguing to give you the best answer' angle is inherently shareable.\n\n"
            "2. **Retention**: Users stay when they see the proof section. "
            "Make 'why this answer is better' the hero feature, not a footnote.\n\n"
            "3. **Monetization**: Don't overcomplicate. Simple per-query pricing after free tier. "
            "$0.10-0.50 per query, or $29/mo unlimited.\n\n"
            "4. **Competition**: ChatGPT is the elephant. Position as 'second opinion' not replacement."
        ),
        "latency_range": (3000, 10000),
    },
    "claude-haiku-4-5-20251001": {
        "research": (
            "## Quick Analysis (Haiku)\n\n"
            "1. Focus on speed and simplicity for initial launch\n"
            "2. SEO-driven acquisition with comparison content\n"
            "3. Freemium with generous free tier to build word-of-mouth\n"
            "4. B2B enterprise tier as growth driver"
        ),
        "latency_range": (1000, 3000),
    },
}

def _build_pe_output(is_multi: bool) -> str:
    if is_multi:
        phases = json.dumps([
            {"name": "Market & Competitive Analysis", "prompt": "Analyze the competitive landscape, market size, and key trends. Identify positioning opportunities and gaps."},
            {"name": "Growth & Distribution Strategy", "prompt": "Design a growth strategy covering acquisition channels, retention tactics, and scaling approach."},
            {"name": "Pricing & Monetization", "prompt": "Recommend pricing model, tier structure, and monetization strategy based on the market analysis."},
        ])
    else:
        phases = json.dumps([
            {"name": "Strategic Analysis", "prompt": "Provide a comprehensive strategic analysis covering positioning, growth, pricing, and differentiation."},
        ])
    return json.dumps({
        "refined_prompt": "Analyze the strategic landscape and create an actionable plan covering positioning, growth channels, pricing, and competitive differentiation.",
        "is_multi_phase": is_multi,
        "phases": json.loads(phases),
    })

_MOCK_STRATEGIST = (
    "## Synthesized Strategy\n\n"
    "After analyzing outputs from {model_count} AI models, here are the key findings:\n\n"
    "### Consensus Points\n"
    "All models agree on:\n"
    "- SEO and content marketing as primary acquisition channel\n"
    "- Freemium pricing model with ~$29/mo professional tier\n"
    "- The 'proof mechanism' as a key differentiator\n\n"
    "### Key Disagreements\n"
    "- **GTM approach**: GPT and Grok favor aggressive launch (Product Hunt), "
    "while Claude and Gemini prefer organic buildup\n"
    "- **Pricing**: Range from $19/mo (Gemini) to $99/mo (GPT) for pro tier\n\n"
    "### Unique Insights\n"
    "- Claude highlighted the 'second opinion' positioning angle\n"
    "- DeepSeek identified B2B API access as an untapped revenue stream\n"
    "- Grok emphasized shareability of the multi-AI comparison concept\n\n"
    "### Recommended Direction\n"
    "Combine organic SEO foundation with a targeted Product Hunt launch. "
    "Price at $29/mo with 5 free runs. Lead with the proof mechanism as hero feature."
)

_MOCK_DECISION = (
    "# Final Strategy: Multi-AI Answer Engine Growth Plan\n\n"
    "## Executive Summary\n"
    "Launch a multi-AI orchestration platform positioned as 'the definitive answer, "
    "not just another AI model.' Differentiate through transparent multi-model comparison "
    "and the proof mechanism.\n\n"
    "## Phase 1: Foundation (Months 1-2)\n"
    "- Build 50 SEO comparison pages targeting 'best AI for [task]' queries\n"
    "- Launch freemium tier with 5 free runs/month\n"
    "- Set up $29/mo Pro tier, $99/mo Team tier\n\n"
    "## Phase 2: Launch (Months 3-4)\n"
    "- Product Hunt launch with 'AI models debate to find the best answer' angle\n"
    "- Hacker News deep-dive post on multi-model synthesis methodology\n"
    "- Outreach to 20 AI newsletter writers\n\n"
    "## Phase 3: Scale (Months 5-8)\n"
    "- Launch B2B API for developers ($0.10-0.50/query)\n"
    "- Enterprise tier with custom model selection\n"
    "- Affiliate program with AI education creators\n\n"
    "## Key Metrics\n"
    "- Target: 1,000 free users, 100 paid users by Month 4\n"
    "- CAC target: < $20 (SEO-driven)\n"
    "- Retention target: 60% M1 retention\n\n"
    "## Risk Mitigation\n"
    "- API costs: Tiered model pools keep margins at 40%+ for standard mode\n"
    "- Competition: 'Proof mechanism' creates defensible UX moat\n"
    "- Quality: Multi-phase context propagation ensures depth others can't match"
)


class MockProvider(BaseProvider):
    """Mock provider that returns deterministic test outputs."""

    name = "mock"
    provider = "mock"

    def __init__(self, api_key: str = "mock-key", model_id: str = "mock",
                 timeout: int = 30, fail_mode: str = "none"):
        super().__init__(api_key=api_key, model_id=model_id, timeout=timeout)
        self.name = model_id
        self.fail_mode = fail_mode  # "none", "timeout", "error", "empty"

    async def complete(self, prompt: str, system: str = "", web_search: bool = False) -> ModelResult:
        start = time.time()
        model_data = _MOCK_OUTPUTS.get(self.name, _MOCK_OUTPUTS.get("gpt-4o-mini"))

        # Simulate failure modes
        if self.fail_mode == "timeout":
            await asyncio.sleep(2)
            return self._make_result("timeout", error="Mock timeout", start_time=start)
        if self.fail_mode == "error":
            return self._make_result("error", error="Mock HTTP 500 error", start_time=start)
        if self.fail_mode == "empty":
            return self._make_result("success", response_content="", start_time=start)

        # Simulate realistic latency (scaled down 10x for testing)
        lo, hi = model_data.get("latency_range", (1000, 3000))
        delay_ms = random.randint(lo // 10, hi // 10)
        await asyncio.sleep(delay_ms / 1000)

        # Check if this is a PE call (system prompt contains "prompt engineer")
        if "prompt engineer" in system.lower() or "json" in system.lower():
            is_multi = len(prompt) > 200 or "multi-phase" in prompt.lower() or "deep" in prompt.lower()
            content = _build_pe_output(is_multi)
            return self._make_result("success", response_content=content, start_time=start)

        # Check if this is a strategist call
        if "strategist" in system.lower() or "synthesiz" in system.lower() or "synthesise" in system.lower():
            content = _MOCK_STRATEGIST.replace("{model_count}", "5")
            return self._make_result("success", response_content=content, start_time=start)

        # Check if this is a decision maker call
        if "decision" in system.lower() or "final" in system.lower():
            return self._make_result("success", response_content=_MOCK_DECISION, start_time=start)

        # Default: research output
        content = model_data.get("research", "Mock research output for " + self.name)
        return self._make_result("success", response_content=content, start_time=start)
