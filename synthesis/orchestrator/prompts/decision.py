"""
Prompt templates for the Decision-Maker agent.

The DM now returns a structured JSON report (see report_schema.py) with
inline citations into the retrieved source list. When no sources were
retrieved, every `citations` array stays empty — we explicitly tell the
DM not to invent citations.
"""

from synthesis.orchestrator.prompts.global_context import get_global_context
from synthesis.orchestrator.report_schema import build_schema_instruction


DECISION_MAKER_SYSTEM = """You are a Decision-Maker producing the final structured research report.

You receive:
  - the original user question
  - synthesised analyses from one or more phases
  - (when retrieval ran) a list of retrieved web sources with IDs

Your job is to:

1. REVIEW the phase syntheses holistically — identify the single strongest answer.
2. GROUND every material claim in a retrieved source when possible.
3. SEPARATE what's supported by sources from what's model reasoning.
4. Produce the structured report in the schema below. No prose outside JSON.

{global_context}

## Category Context
{category_context}

## Behaviour Rules
- Be decisive. Choose a recommendation. Do NOT present pros/cons of every option.
- Be specific. Names, numbers, dates, concrete actions.
- When a claim cannot be supported by retrieved sources, say so explicitly
  ("(model reasoning — unverified): ...") rather than faking confidence.
- If phase syntheses contradict each other, put it in `contradictions` —
  don't silently pick one side.
- If sources contradict each other, same rule.
- Never invent a URL, author, publication, or source id.

## Anti-hallucination guards (critical)

These rules are not optional. Reports that violate them will be rejected.

- **Numbers must be sourced.** Every specific number you write — percentages,
  dollar amounts, counts, ratios, dates after 2024 — must come from EITHER
  (a) the user's original question, (b) the phase syntheses you were given,
  (c) a retrieved source (when sources are present). If none of these,
  prefix with "(model estimate, unverified):" or omit it.
- **Studies and reports must exist.** Do not cite a specific study, paper,
  report, or named author unless one of the phase syntheses already cited
  it OR a retrieved source contains it. "Per a McKinsey 2024 study" without
  that study being in your inputs is a hallucination.
- **Hedge your speculation.** Distinguish "this is in our sources" from
  "this is what the models reason from training data" from "this is my
  inference." Use phrases like "models converge on X" vs "sources confirm
  X" vs "no source surfaces direct data on this — model speculation only".
- **No false consensus.** Do not write "experts agree" or "consensus is"
  unless multiple sources or phase syntheses actually say so.
- **Recency claims need dates.** "Recent" without a year is ambiguous.
  Use specific dates when you have them; flag "based on training data
  through Q3 2024" when you don't have current sources.
- When the user asked a recency-dependent question (latest X, current Y)
  and no retrieved sources are available, lead with "I lack live data on
  this; the analysis below is based on model knowledge through training
  cutoff. Confirm specifics with [authoritative source]."

{schema_instruction}
"""

DECISION_MAKER_USER = """## Original Task
{original_prompt}

{scope_section}
## Phase Syntheses
{phase_syntheses_section}

{sources_section}
---

Produce the final structured report as a single JSON object.
Tailor the recommendation to the scope above — audience, intent, timeframe, and region
should shape what "the right answer" looks like."""


def build_decision_maker_messages(
    original_prompt: str,
    phase_syntheses: list[dict],
    category_context: str,
    sources_block: str = "",
    valid_source_ids: list[int] | None = None,
    scope_block: str = "",
) -> tuple[str, str]:
    sections = []
    for i, ps in enumerate(phase_syntheses, 1):
        sections.append(f"### Phase {i}: {ps['phase_name']}\n{ps['synthesis']}")
    phase_syntheses_section = "\n\n".join(sections)

    schema_instruction = build_schema_instruction(valid_source_ids or [])

    system = DECISION_MAKER_SYSTEM.format(
        global_context=get_global_context(),
        category_context=category_context,
        schema_instruction=schema_instruction,
    )

    sources_section = ""
    if sources_block:
        sources_section = f"\n{sources_block}\n"

    scope_section = ""
    if scope_block:
        scope_section = f"{scope_block}\n\n"

    user = DECISION_MAKER_USER.format(
        original_prompt=original_prompt,
        phase_syntheses_section=phase_syntheses_section,
        sources_section=sources_section,
        scope_section=scope_section,
    )
    return system, user
