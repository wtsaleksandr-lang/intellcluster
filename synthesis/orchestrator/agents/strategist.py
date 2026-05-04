"""
Strategist Agent (Phase-Level Synthesis)
"""

from synthesis.orchestrator.prompts.categories import get_category_context
from synthesis.orchestrator.prompts.synthesis import build_strategist_messages
from synthesis.orchestrator.providers import call_with_role_fallback
from shared.providers.base import ModelResult


async def run_strategist(
    refined_prompt: str,
    phase_name: str,
    phase_number: int,
    total_phases: int,
    model_results: list[ModelResult],
    category: str,
    prior_phase_context: str = "",
    expected_models: int = 0,
    failed_models: list[str] | None = None,
    tier: str = "standard",
    consensus_text: str = "",
) -> str:
    category_context = get_category_context(category)

    # Tag researcher output with role only when role specialization is on
    # (gated separately from SYNTHESIS_V2 — see pipeline.py).
    import os as _os
    _v2 = _os.environ.get("SYNTHESIS_ROLES", "").lower() == "true"
    if _v2:
        from synthesis.orchestrator.research_roles import get_role_for_model
        model_output_dicts = [
            {
                "model_name": f"{r.model_name} ({get_role_for_model(r.model_name)})",
                "response_content": r.response_content or "(no response)",
            }
            for r in model_results
            if r.status == "success" and r.response_content
        ]
    else:
        model_output_dicts = [
            {
                "model_name": r.model_name,
                "response_content": r.response_content or "(no response)",
            }
            for r in model_results
            if r.status == "success" and r.response_content
        ]

    system_msg, user_msg = build_strategist_messages(
        refined_prompt=refined_prompt,
        phase_name=phase_name,
        phase_number=phase_number,
        total_phases=total_phases,
        model_results=model_output_dicts,
        category_context=category_context,
        prior_phase_context=prior_phase_context,
        expected_models=expected_models,
        failed_models=failed_models,
        consensus_text=consensus_text,
    )

    result, provider_used = await call_with_role_fallback(
        role="strategist",
        prompt=user_msg,
        system=system_msg,
        tier=tier,
        # System prompt is stable per category — cache for ~90% input savings
        # on the Anthropic path within the 5-min cache window.
        cache_system=True,
    )

    if result.status != "success" or not result.response_content:
        fallback_parts = []
        for r in model_output_dicts:
            fallback_parts.append(f"[{r['model_name']}]: {r['response_content'][:500]}")
        return "Strategist synthesis failed (all providers). Raw model outputs:\n\n" + "\n\n".join(fallback_parts)

    return result.response_content
