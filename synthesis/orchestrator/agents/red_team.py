"""
Red Team Critique — Optional stage triggered by risk conditions.

Activated ONLY when:
- agreement_score < 0.4 (high model disagreement)
- category is risk/regulatory
- contradictions count > 2
- high-stakes commercial decision detected

Uses cheapest available model. Finds hidden risks, weak assumptions, missed downsides.
Output is appended to DM input, not a separate pipeline stage.
"""

from synthesis.config import settings
from synthesis.orchestrator.providers import call_with_role_fallback


RED_TEAM_SYSTEM = """You are a devil's advocate analyst. Your job is to find flaws in a strategic recommendation.

Be critical but constructive. Focus on:
1. Hidden risks not mentioned
2. Weak assumptions being made
3. Missing downside scenarios
4. Overconfidence in conclusions
5. Practical implementation obstacles

Keep your critique to 3-5 specific points. Each point should be actionable.
Do NOT restate the strategy — only critique it."""

RED_TEAM_USER = """Original question: {question}

Proposed strategy/recommendation:
{strategy}

Consensus agreement score: {agreement_score:.0%}
Contradictions detected: {contradiction_count}

Find the flaws. What could go wrong? What assumptions are weak?"""

# Categories that warrant Red Team by default
RED_TEAM_CATEGORIES = {"deep_research", "competitor_market_research", "decision_strategy"}


def should_trigger_red_team(
    consensus: dict,
    category: str,
) -> bool:
    """Determine if Red Team critique should run."""
    score = consensus.get("agreement_score", 1.0)
    contradictions = len(consensus.get("contradictions", []))

    # Low agreement
    if score < 0.4:
        return True

    # Many contradictions
    if contradictions > 2:
        return True

    # Risk/regulatory categories with moderate disagreement
    if category in RED_TEAM_CATEGORIES and score < 0.6:
        return True

    return False


async def run_red_team(
    question: str,
    strategy: str,
    consensus: dict,
    tier: str = "standard",
) -> str | None:
    """Run Red Team critique on the synthesized strategy.

    Returns critique text or None if it fails.
    Uses cheapest model available.
    """
    system = RED_TEAM_SYSTEM
    user = RED_TEAM_USER.format(
        question=question[:1000],
        strategy=strategy[:3000],
        agreement_score=consensus.get("agreement_score", 0.5),
        contradiction_count=len(consensus.get("contradictions", [])),
    )

    # Always use cost_efficient for red team
    result, provider_used = await call_with_role_fallback(
        role="strategist",
        prompt=user,
        system=system,
        tier="cost_efficient",
    )

    if result.status == "success" and result.response_content:
        return result.response_content

    return None
