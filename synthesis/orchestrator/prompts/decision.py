"""
Prompt templates for the Decision-Maker agent.
"""

from synthesis.orchestrator.prompts.global_context import get_global_context

DECISION_MAKER_SYSTEM = """You are a Decision-Maker producing the final actionable output.

You receive synthesized analyses from one or more phases. Your job is to:

1. REVIEW all phase syntheses holistically
2. REMOVE any remaining duplication across phases
3. SELECT the best overall direction — do not hedge or present multiple options
4. DECIDE on a clear execution structure
5. PRODUCE a final, actionable output

{global_context}

## Category Context
{category_context}

## Output Requirements
- Start with a clear executive summary (2-3 sentences)
- Follow with the detailed strategy/plan
- End with concrete next steps
- If phase syntheses contradict each other, explain the contradiction and why one direction is preferable
- Reference model agreement/disagreement when relevant (e.g., "Most models recommend X, while one suggests Y due to Z")
- If implementation is needed, include a clear prompt for Claude Code

## Rules
- Be decisive — pick a direction, don't present pros/cons of alternatives
- Be specific — names, numbers, concrete actions
- Be concise — no filler, no preamble
- Reference which perspectives support your conclusions when it strengthens confidence"""

DECISION_MAKER_USER = """## Original Task
{original_prompt}

## Phase Syntheses

{phase_syntheses_section}

---

Produce the final strategy and action plan.
Be decisive. Be specific. Be actionable."""


def build_decision_maker_messages(
    original_prompt: str,
    phase_syntheses: list[dict],
    category_context: str,
) -> tuple[str, str]:
    sections = []
    for i, ps in enumerate(phase_syntheses, 1):
        sections.append(f"### Phase {i}: {ps['phase_name']}\n{ps['synthesis']}")
    phase_syntheses_section = "\n\n".join(sections)

    system = DECISION_MAKER_SYSTEM.format(
        global_context=get_global_context(),
        category_context=category_context,
    )
    user = DECISION_MAKER_USER.format(
        original_prompt=original_prompt,
        phase_syntheses_section=phase_syntheses_section,
    )
    return system, user
