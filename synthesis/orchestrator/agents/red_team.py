"""
Red Team Critique — Optional stage triggered by risk conditions.

Activated when:
- agreement_score < 0.4 (high model disagreement), OR
- contradictions count > 2, OR
- category is risk/regulatory with score < 0.6

Grounded Red Team (P6): when retrieved sources are present, the critique
MUST cite them by id when challenging a claim. The prompt explicitly
tells the Red Team to flag:

  * unsupported claims (no source backing them)
  * outdated claims (stale source dates)
  * weak sources (single low-authority source)
  * contradictions (sources disagreeing with each other or with the strategy)
  * overconfident conclusions

If no sources were retrieved, the Red Team falls back to its previous
"find flaws in reasoning" behaviour — still useful, just less grounded.

Uses cheapest available model. Output is appended as an extra phase to
the Decision-Maker input.
"""

from synthesis.orchestrator.providers import call_with_role_fallback


RED_TEAM_SYSTEM_GROUNDED = """You are a devil's advocate analyst reviewing a research strategy.

You have access to retrieved web sources. Your critique MUST be grounded
in those sources where possible.

Focus on:
1. UNSUPPORTED CLAIMS — claims in the strategy that no retrieved source backs.
2. OUTDATED CLAIMS — claims supported only by old (>18 months) sources.
3. WEAK SOURCES — single sources from low-authority domains.
4. CONTRADICTIONS — where sources disagree with the strategy or with each other.
5. OVERCONFIDENCE — where the strategy sounds certain but evidence is thin.

Rules:
- When you challenge a claim, cite the source id you're using (e.g. "[3] is from 2019").
- If you assert "no source supports this," say so plainly — do not invent a citation.
- Keep the critique to 3–6 specific bullets. Each one actionable.
- Do NOT restate the strategy. Critique only."""


RED_TEAM_SYSTEM_UNGROUNDED = """You are a devil's advocate analyst. Your job is to find flaws in a strategic recommendation.

Be critical but constructive. Focus on:
1. Hidden risks not mentioned
2. Weak assumptions being made
3. Missing downside scenarios
4. Overconfidence in conclusions
5. Practical implementation obstacles

Keep your critique to 3-5 specific points. Each point should be actionable.
Do NOT restate the strategy — only critique it."""


RED_TEAM_USER_GROUNDED = """Original question: {question}

Proposed strategy/recommendation:
{strategy}

Consensus agreement score: {agreement_score:.0%}
Contradictions detected: {contradiction_count}

{sources_block}

Find the flaws. Ground each critique in a source id where you can."""


RED_TEAM_USER_UNGROUNDED = """Original question: {question}

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
    """Determine if Red Team critique should run.

    v2 (SYNTHESIS_V2=true): always fire. The audit identified the red team
    as one of the genuinely-useful structural agents in the pipeline; gating
    it on disagreement signal means it only catches cases where the models
    happened to disagree publicly, missing cases where they confidently
    agree on a wrong answer.
    """
    import os
    if os.environ.get("SYNTHESIS_V2", "").lower() == "true":
        return True

    score = consensus.get("agreement_score", 1.0)
    contradictions = len(consensus.get("contradictions", []))

    if score < 0.4:
        return True
    if contradictions > 2:
        return True
    if category in RED_TEAM_CATEGORIES and score < 0.6:
        return True
    return False


async def run_red_team(
    question: str,
    strategy: str,
    consensus: dict,
    tier: str = "standard",
    sources_block: str = "",
) -> str | None:
    """Run Red Team critique on the synthesised strategy.

    Returns critique text or None if it fails.
    Uses cheapest model available.
    Grounded mode activates when `sources_block` is non-empty.
    """
    grounded = bool(sources_block.strip())

    if grounded:
        system = RED_TEAM_SYSTEM_GROUNDED
        user = RED_TEAM_USER_GROUNDED.format(
            question=question[:1000],
            strategy=strategy[:3000],
            agreement_score=consensus.get("agreement_score", 0.5),
            contradiction_count=len(consensus.get("contradictions", [])),
            sources_block=sources_block,
        )
    else:
        system = RED_TEAM_SYSTEM_UNGROUNDED
        user = RED_TEAM_USER_UNGROUNDED.format(
            question=question[:1000],
            strategy=strategy[:3000],
            agreement_score=consensus.get("agreement_score", 0.5),
            contradiction_count=len(consensus.get("contradictions", [])),
        )

    result, _provider_used = await call_with_role_fallback(
        role="strategist",
        prompt=user,
        system=system,
        tier="cost_efficient",
    )

    if result.status == "success" and result.response_content:
        return result.response_content

    return None
