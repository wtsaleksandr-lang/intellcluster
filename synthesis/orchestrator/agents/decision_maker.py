"""
Decision-Maker Agent (Cross-Phase Synthesis)
- Reviews all strategist outputs across phases
- Removes duplication
- Selects best overall direction
- Produces final strategy + implementation plan
- Falls back through available providers if configured one fails
"""

from synthesis.orchestrator.prompts.categories import get_category_context
from synthesis.orchestrator.prompts.decision import build_decision_maker_messages
from synthesis.orchestrator.providers import call_with_role_fallback


async def run_decision_maker(
    original_prompt: str,
    phase_syntheses: list[dict],
    category: str,
    tier: str = "standard",
) -> str:
    """Run the Decision-Maker agent to produce the final output."""
    category_context = get_category_context(category)

    system_msg, user_msg = build_decision_maker_messages(
        original_prompt=original_prompt,
        phase_syntheses=phase_syntheses,
        category_context=category_context,
    )

    result, provider_used = await call_with_role_fallback(
        role="decision_maker",
        prompt=user_msg,
        system=system_msg,
        tier=tier,
    )

    if result.status != "success" or not result.response_content:
        if phase_syntheses:
            last = phase_syntheses[-1]
            return (
                f"Decision-Maker synthesis failed (all providers). Last phase output:\n\n"
                f"## {last['phase_name']}\n{last['synthesis']}"
            )
        return "Decision-Maker failed and no phase outputs available."

    return result.response_content
