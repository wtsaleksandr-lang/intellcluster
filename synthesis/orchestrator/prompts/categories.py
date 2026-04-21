"""
9 dropdown categories with explanations and prompt templates.
"""

CATEGORIES = {
    "decision_strategy": {
        "label": "Decision & Strategy",
        "description": "Analyze decisions under uncertainty — risks, trade-offs, and clear recommendations.",
        "research_focus": "decision analysis, risk assessment, trade-off evaluation, strategic reasoning, scenario planning",
        "output_format": "decision framework with pros/cons, risk analysis, and clear recommendation",
        "hint": "Best for making decisions with high uncertainty. Analyzes risks, trade-offs, and recommends a clear direction.",
        "templates": [
            {
                "label": "Decision Analysis",
                "content": (
                    "I need help deciding:\n\n"
                    "Situation: [describe situation]\n\n"
                    "Options:\n- [option 1]\n- [option 2]\n- [option 3]\n\n"
                    "Constraints: [budget, time, risk tolerance]\n\n"
                    "Goal: [what outcome you want]\n\n"
                    "Provide:\n- pros/cons\n- risks\n- best recommendation"
                ),
            },
            {
                "label": "Opportunity Evaluation",
                "content": (
                    "Evaluate whether I should pursue this:\n\n"
                    "Idea: [describe]\n"
                    "Target market: [who]\n"
                    "Concerns: [risks]\n\n"
                    "Give a clear recommendation with reasoning."
                ),
            },
        ],
    },
    "competitor_market_research": {
        "label": "Competitor & Market Research",
        "description": "Analyze competitors, pricing, funnels, market gaps, and differentiation opportunities.",
        "research_focus": "competitor analysis, pricing comparison, funnel teardown, market gaps, acquisition channels, differentiation",
        "output_format": "competitive analysis with gaps, opportunities, and strategic recommendations",
        "hint": "Analyzes competitors, pricing, offers, funnels, and identifies gaps and opportunities.",
        "templates": [
            {
                "label": "Competitor Analysis",
                "content": (
                    "Research top competitors in:\n\n"
                    "Industry: [insert]\n\n"
                    "Analyze:\n- pricing\n- offers\n- funnels\n- acquisition channels\n\n"
                    "Find gaps and recommend strategy."
                ),
            },
            {
                "label": "Market Breakdown",
                "content": (
                    "Break down how leading companies in [industry] acquire customers and monetize.\n\n"
                    "Then suggest how I can outperform them."
                ),
            },
        ],
    },
    "business_ideas_validation": {
        "label": "Business Ideas & Validation",
        "description": "Validate ideas, estimate demand, competition, risk, and profitability potential.",
        "research_focus": "idea validation, demand estimation, competitive landscape, risk analysis, profitability modeling",
        "output_format": "validation report with demand, competition, risks, and profitability estimate",
        "hint": "Validates ideas, demand, competition, risk, and profitability potential.",
        "templates": [
            {
                "label": "Idea Validation",
                "content": (
                    "Evaluate this business idea:\n\n"
                    "Idea: [describe]\n"
                    "Target audience: [who]\n\n"
                    "Estimate:\n- demand\n- competition\n- risks\n- profitability\n\n"
                    "Give honest validation."
                ),
            },
            {
                "label": "Quick Validation",
                "content": "Is this idea worth pursuing now?\n\n[describe idea]\n\nExplain timing, risks, and upside.",
            },
        ],
    },
    "marketing_growth": {
        "label": "Marketing & Growth Strategy",
        "description": "Generate acquisition strategies, messaging, channel ideas, and growth tactics.",
        "research_focus": "acquisition channels, ad copy, messaging strategy, growth tactics, funnel strategy, audience targeting",
        "output_format": "marketing strategy with channels, messaging, ad angles, and growth playbook",
        "hint": "Generates acquisition strategy, messaging, channel ideas, and growth tactics.",
        "templates": [
            {
                "label": "Marketing Strategy",
                "content": (
                    "Create a marketing strategy for:\n\n"
                    "Product: [describe]\n"
                    "Audience: [who]\n\n"
                    "Include:\n- acquisition channels\n- ad angles\n- messaging\n- funnel strategy"
                ),
            },
            {
                "label": "First Customers",
                "content": "How should I get my first customers for [product/service]?",
            },
        ],
    },
    "product_offer_design": {
        "label": "Product & Offer Design",
        "description": "Design offers, pricing structure, upsells, and value positioning.",
        "research_focus": "value proposition, offer design, pricing tiers, bundling, upsells, positioning",
        "output_format": "offer design with pricing, bundles, upsells, and positioning strategy",
        "hint": "Designs offers, pricing structure, upsells, and value positioning.",
        "templates": [
            {
                "label": "Offer Design",
                "content": (
                    "Design a compelling offer for:\n\n"
                    "Product: [describe]\n\n"
                    "Include:\n- pricing\n- bundles\n- upsells\n- positioning"
                ),
            },
            {
                "label": "Offer Improvement",
                "content": "How should I package this into a stronger offer?\n\n[describe current offer]",
            },
        ],
    },
    "funnel_conversion": {
        "label": "Funnel & Conversion Optimization",
        "description": "Improve landing pages, conversion flow, CTA placement, and sales logic.",
        "research_focus": "conversion optimization, landing page structure, CTA strategy, objection handling, sales flow",
        "output_format": "conversion optimization plan with structure, CTAs, and specific improvements",
        "hint": "Improves landing pages, conversion flow, CTA placement, and sales logic.",
        "templates": [
            {
                "label": "Funnel Optimization",
                "content": (
                    "Optimize this funnel:\n\n"
                    "Product: [describe]\n"
                    "Goal: [increase conversions]\n\n"
                    "Suggest:\n- structure\n- CTA placement\n- improvements"
                ),
            },
            {
                "label": "Conversion Rate",
                "content": "How can I improve conversion rate on this offer page?\n\n[describe page and current metrics]",
            },
        ],
    },
    "comparison_evaluation": {
        "label": "Comparison & Evaluation",
        "description": "Compare tools, options, strategies, or products and recommend the strongest choice.",
        "research_focus": "comparative analysis, feature comparison, cost-benefit analysis, decision matrices",
        "output_format": "comparison matrix with strengths, weaknesses, and clear recommendation",
        "hint": "Compares tools, options, strategies, or products and recommends the strongest choice.",
        "templates": [
            {
                "label": "Option Comparison",
                "content": (
                    "Compare these options:\n\n"
                    "Options:\n- [option 1]\n- [option 2]\n- [option 3]\n\n"
                    "Criteria: [price, quality, speed, etc.]\n\n"
                    "Give:\n- strengths/weaknesses\n- best choice\n- why"
                ),
            },
            {
                "label": "Quick Compare",
                "content": "Which of these is best for my situation and why?\n\n[list options and context]",
            },
        ],
    },
    "ai_systems_automation": {
        "label": "AI Systems & Automation",
        "description": "Design AI workflows, automation systems, and SaaS/internal tooling logic.",
        "research_focus": "AI workflow design, automation architecture, tool integration, prompt engineering, agent design",
        "output_format": "system architecture with workflow, tools, implementation plan, and cost estimates",
        "hint": "Designs AI workflows, automation pipelines, and tool integrations.",
        "templates": [
            {
                "label": "AI System Design",
                "content": (
                    "Design an AI-powered system for:\n\n"
                    "Use case: [describe]\n\n"
                    "Include:\n- workflow\n- automation\n- tools\n- architecture"
                ),
            },
            {
                "label": "Automation",
                "content": "How should I automate this process with AI and minimal overhead?\n\n[describe current manual process]",
            },
        ],
    },
    "deep_research": {
        "label": "Deep Research (Multi-Phase)",
        "description": "Run deeper multi-phase analysis for complex topics with layered synthesis.",
        "research_focus": "deep analysis, multi-phase research, pattern identification, structured insights, evidence synthesis",
        "output_format": "structured research report with insights, patterns, evidence, and conclusions",
        "hint": "Runs deeper multi-phase analysis for complex topics with layered synthesis.",
        "templates": [
            {
                "label": "Deep Research",
                "content": (
                    "Conduct deep research on:\n\n"
                    "Topic: [describe]\n\n"
                    "Provide:\n- structured insights\n- patterns\n- conclusions"
                ),
            },
            {
                "label": "Multi-Phase Analysis",
                "content": "Run a deep multi-phase analysis of this topic and produce a final recommendation.\n\n[describe topic]",
            },
        ],
    },
}


def get_category(key: str) -> dict:
    return CATEGORIES[key]


def get_category_context(key: str) -> str:
    cat = CATEGORIES[key]
    return (
        f"Category: {cat['label']}\n"
        f"Description: {cat['description']}\n"
        f"Research Focus: {cat['research_focus']}\n"
        f"Expected Output Format: {cat['output_format']}"
    )
