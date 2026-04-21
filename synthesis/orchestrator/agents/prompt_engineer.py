"""
Prompt Engineer Agent
- Cleans and clarifies user input
- Determines single-phase vs multi-phase
- Generates structured prompts
- Falls back through available providers if configured one fails
"""

import json
import re

from synthesis.config import settings
from synthesis.orchestrator.prompts.categories import get_category_context
from synthesis.orchestrator.prompts.meta_prompts import build_prompt_engineer_messages
from synthesis.orchestrator.providers import call_with_role_fallback


def _parse_json_response(text: str) -> dict | None:
    """Strict JSON parsing with fallback for markdown-wrapped responses."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip markdown code fences
    pattern = r"```(?:json)?\s*([\s\S]*?)```"
    match = re.search(pattern, text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try to find JSON object in the text
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start:brace_end + 1])
        except json.JSONDecodeError:
            pass

    return None


def _validate_parsed(data: dict) -> tuple[dict | None, str]:
    """Validate and normalize parsed Prompt Engineer output.
    Returns (validated_data, error_reason). error_reason is empty on success.
    """
    refined = data.get("refined_prompt", "")
    is_multi = data.get("is_multi_phase", False)
    phases = data.get("phases", [])

    if not refined or not isinstance(refined, str):
        return None, "missing or invalid refined_prompt"

    if not isinstance(phases, list) or len(phases) == 0:
        return None, "missing or empty phases list"

    valid_phases = []
    for p in phases[:settings.max_phases]:
        if isinstance(p, dict) and p.get("name") and p.get("prompt"):
            valid_phases.append({
                "name": str(p["name"]),
                "prompt": str(p["prompt"]),
            })

    if len(valid_phases) == 0:
        return None, f"no valid phases found in {len(phases)} entries"

    return {
        "refined_prompt": refined,
        "is_multi_phase": bool(is_multi) and len(valid_phases) > 1,
        "phases": valid_phases,
    }, ""


async def run_prompt_engineer(
    user_prompt: str,
    category: str,
    quick_mode: bool = False,
    attachments: list[dict] | None = None,
    tier: str = "standard",
) -> dict:
    """Run the Prompt Engineer agent.

    Tries configured PE provider for the given tier, falls back to others.

    Returns:
        {
            "refined_prompt": str,
            "is_multi_phase": bool,
            "phases": [{"name": str, "prompt": str}, ...],
            "used_fallback": bool,
            "provider_used": str,
        }
    """
    category_context = get_category_context(category)
    system_msg, user_msg = build_prompt_engineer_messages(
        user_prompt=user_prompt,
        category_context=category_context,
        max_phases=settings.max_phases,
        quick_mode=quick_mode,
        attachments=attachments,
    )

    result, provider_used = await call_with_role_fallback(
        role="prompt_engineer",
        prompt=user_msg,
        system=system_msg,
        tier=tier,
    )

    used_fallback = provider_used != settings.prompt_engineer_model

    if result.status != "success" or not result.response_content:
        fb = _fallback(user_prompt)
        fb["used_fallback"] = True
        fb["provider_used"] = "none (all providers failed)"
        return fb

    parsed = _parse_json_response(result.response_content)
    if not parsed:
        fb = _fallback(user_prompt)
        fb["used_fallback"] = True
        fb["provider_used"] = provider_used + " (JSON parse failed)"
        return fb

    validated, validation_error = _validate_parsed(parsed)
    if not validated:
        fb = _fallback(user_prompt)
        fb["used_fallback"] = True
        fb["provider_used"] = provider_used + f" (validation: {validation_error})"
        return fb

    validated["used_fallback"] = used_fallback
    validated["provider_used"] = provider_used
    return validated


def _fallback(user_prompt: str) -> dict:
    """Fallback when prompt engineer fails: single-phase with original prompt."""
    return {
        "refined_prompt": user_prompt,
        "is_multi_phase": False,
        "phases": [{"name": "Main Task", "prompt": user_prompt}],
    }
