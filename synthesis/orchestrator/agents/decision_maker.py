"""
Decision-Maker Agent (Cross-Phase Synthesis)

Produces the final structured report (see orchestrator/report_schema.py).
Accepts the retrieved sources block and the valid-citation-id list, so
the DM can ground claims and we can strip any invented [N] refs before
rendering.

Returns a tuple:
    (StructuredReport, raw_text)

- On successful JSON parse, StructuredReport is fully populated.
- On parse failure, we wrap the raw model output in a minimal report so
  the UI still renders something coherent.
- On provider failure (all fallbacks exhausted), we return a
  deterministic error report built from the last available phase
  synthesis.
"""

from synthesis.orchestrator.prompts.categories import get_category_context
from synthesis.orchestrator.prompts.decision import build_decision_maker_messages
from synthesis.orchestrator.providers import call_with_role_fallback
from synthesis.orchestrator.report_schema import (
    parse_structured_report,
    text_fallback_report,
)
from synthesis.orchestrator.types import ConfidenceScore, StructuredReport


async def run_decision_maker(
    original_prompt: str,
    phase_syntheses: list[dict],
    category: str,
    confidence: ConfidenceScore,
    tier: str = "standard",
    sources_block: str = "",
    valid_source_ids: list[int] | None = None,
    scope_block: str = "",
) -> tuple[StructuredReport, str]:
    """Run the Decision-Maker agent. Returns (StructuredReport, raw_text)."""
    category_context = get_category_context(category)

    system_msg, user_msg = build_decision_maker_messages(
        original_prompt=original_prompt,
        phase_syntheses=phase_syntheses,
        category_context=category_context,
        sources_block=sources_block,
        valid_source_ids=valid_source_ids or [],
        scope_block=scope_block,
    )

    result, provider_used = await call_with_role_fallback(
        role="decision_maker",
        prompt=user_msg,
        system=system_msg,
        tier=tier,
        # Stable per category — cache for ~90% input savings on Anthropic.
        cache_system=True,
    )

    if result.status != "success" or not result.response_content:
        # All providers failed — build a deterministic fallback from the
        # last phase synthesis so the user still gets something.
        fallback_text = ""
        if phase_syntheses:
            last = phase_syntheses[-1]
            fallback_text = (
                f"Decision-Maker synthesis failed (all providers). "
                f"Last phase output:\n\n## {last['phase_name']}\n{last['synthesis']}"
            )
        else:
            fallback_text = "Decision-Maker failed and no phase outputs available."

        return text_fallback_report(fallback_text, confidence), fallback_text

    raw_text = result.response_content
    report, parse_error = parse_structured_report(
        raw=raw_text,
        confidence=confidence,
        valid_source_ids=valid_source_ids or [],
    )

    if report is not None:
        return report, raw_text

    # JSON parse failed — wrap the raw text so nothing is lost.
    return text_fallback_report(raw_text, confidence), raw_text
