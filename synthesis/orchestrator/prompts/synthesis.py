"""
Prompt templates for the Strategist agent.
"""

from synthesis.orchestrator.prompts.global_context import get_global_context

STRATEGIST_SYSTEM = """You are a Strategic Analyst performing phase-level synthesis.

Your job is NOT to summarize — it is to SYNTHESIZE with analytical rigor.

{global_context}

## Your Tasks

1. COMPARE all model outputs — identify where they agree and disagree
2. EVALUATE the quality of each insight:
   - Strong signal: multiple models independently reached the same conclusion
   - Unique insight: only one model found it, but it's well-reasoned and specific
   - Weak/generic: vague advice anyone could give (REMOVE these)
   - Contradictions: models disagree — evaluate which position is stronger and WHY
3. PRODUCE a single, unified analysis that is BETTER than any individual output
4. Be specific and actionable — no filler, no generic advice

## Category Context
{category_context}

{model_coverage_note}

## Important
- Do NOT just list what each model said
- Do NOT include weak or generic ideas just because multiple models mentioned them
- DO keep unique insights that are well-reasoned even if only one model found them
- DO resolve contradictions with clear reasoning
- DO prioritize actionable specificity over comprehensive coverage"""

STRATEGIST_USER = """## Task
{refined_prompt}

## Phase: {phase_name} ({phase_number} of {total_phases})
{phase_context}

## Model Outputs

{model_outputs_section}

{consensus_section}

---

Synthesize these into ONE clean, actionable analysis for this phase.
Focus on quality over quantity. Remove fluff. Keep what's strong.
{consensus_instruction}"""


def build_strategist_messages(
    refined_prompt: str,
    phase_name: str,
    phase_number: int,
    total_phases: int,
    model_results: list[dict],
    category_context: str,
    prior_phase_context: str = "",
    expected_models: int = 0,
    failed_models: list[str] | None = None,
    consensus_text: str = "",
) -> tuple[str, str]:
    sections = []
    for r in model_results:
        sections.append(f"--- {r['model_name']} ---\n{r['response_content']}")
    model_outputs_section = "\n\n".join(sections)

    phase_context = ""
    if prior_phase_context:
        phase_context = f"\n## Prior Phase Context\n{prior_phase_context}"

    model_coverage_note = ""
    if failed_models:
        model_coverage_note = (
            f"## Model Coverage Warning\n"
            f"Expected {expected_models} models, received {len(model_results)} successful outputs.\n"
            f"Failed/missing models: {', '.join(failed_models)}\n"
            f"Note: with fewer perspectives, confidence in consensus should be reduced. "
            f"Mention this limitation if it affects the analysis quality."
        )

    # Consensus section + instruction
    consensus_section = ""
    consensus_instruction = ""
    if consensus_text:
        consensus_section = f"\n## Pre-Analyzed Consensus\n{consensus_text}"
        consensus_instruction = (
            "Use the pre-analyzed consensus data above to strengthen your synthesis. "
            "High-consensus items are strong signals — lead with these. "
            "Contradictions require explicit resolution. "
            "Preserve unique insights if well-reasoned."
        )

    system = STRATEGIST_SYSTEM.format(
        global_context=get_global_context(),
        category_context=category_context,
        model_coverage_note=model_coverage_note,
    )
    user = STRATEGIST_USER.format(
        refined_prompt=refined_prompt,
        phase_name=phase_name,
        phase_number=phase_number,
        total_phases=total_phases,
        phase_context=phase_context,
        model_outputs_section=model_outputs_section,
        consensus_section=consensus_section,
        consensus_instruction=consensus_instruction,
    )
    return system, user
