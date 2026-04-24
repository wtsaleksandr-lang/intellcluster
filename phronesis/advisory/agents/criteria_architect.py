"""Criteria Architect — builds the weighted rubric for this advisory."""

from __future__ import annotations

import json
from typing import Any

from ..base import Agent
from ..types import AgentOutput


class CriteriaArchitectAgent(Agent):
    name = "criteria_architect"
    tier = "fast"
    temperature = 0.3

    system_prompt = """You are the Criteria Architect. Given an advisory
question, its category, the intake, and the user's MCQ answers, produce a
weighted scoring rubric the analyst agents will use to evaluate options.

PRINCIPLES:
  - 4-7 criteria. Fewer is better if each one is decisive.
  - Weights are integers 1-10. Sum is NOT required to be 100 — this is a
    relative importance scale, not a percentage.
  - The user's top priority (from MCQ answers or intake) should get the
    highest weight; less important factors get lower weight.
  - Criteria names must be specific to this decision, not generic:
      BAD:  "Cost"  "Risk"  "Quality"
      GOOD: "Total cost over 18 months"  "Probability of business failing
            within 2 years"  "Build quality vs. repairability"
  - Add a brief rationale per criterion: why this matters for THIS user
    given what they told us.

CATEGORIES THAT OFTEN BENEFIT FROM SPECIFIC CRITERIA:
  - career: total comp 3yr, learning curve, optionality, team quality,
    stress/health, career narrative
  - purchase: total cost of ownership, longevity, fit-for-workflow,
    opportunity cost, reversibility
  - business: time to profitability, downside if it fails, market pull,
    founder fit, capital burn
  - finance: expected return, downside risk, liquidity, tax implications,
    complexity
  - relocation: cost of living delta, relationship proximity, career impact,
    lifestyle fit, reversibility
  - vendor: feature fit, switching cost, total cost of ownership, support
    quality, vendor viability

Respond ONLY with JSON:

{
  "criteria": [
    {"name": "string", "weight": 1-10, "rationale": "one sentence why"},
    ...
  ]
}
"""

    def build_user(self, *, session, **_) -> str:
        intake = session.intake
        intake_dict = {
            "advisory_question": intake.advisory_question if intake else "",
            "options": intake.options if intake else [],
            "user_goal": intake.user_goal if intake else "",
            "constraints": intake.constraints if intake else [],
            "timeline": intake.timeline if intake else None,
            "budget": intake.budget if intake else None,
            "risk_tolerance": intake.risk_tolerance if intake else None,
        }
        category = session.category or "exploratory"
        answers = [
            {"question_id": a.question_id, "answer": a.answer}
            for a in session.user_answers if a.answer is not None
        ]
        # Map question_id back to question text for context
        q_by_id = {q.id: q.question for q in session.clarifying_questions}
        for a in answers:
            a["question"] = q_by_id.get(a["question_id"], "")
        return (
            f"Category: {category}\n\n"
            f"Intake:\n{json.dumps(intake_dict, indent=2)}\n\n"
            f"User MCQ answers:\n{json.dumps(answers, indent=2)}\n\n"
            "Produce the JSON criteria array now — 4-7 specific, weighted criteria."
        )

    def parse(self, data: dict[str, Any], **_) -> AgentOutput:
        items = data.get("criteria") or []
        bullets = [
            f"{c.get('name', '')} (weight {c.get('weight', 0)})"
            for c in items[:7]
        ]
        return AgentOutput(
            agent=self.name,
            status="ok",
            summary=f"{len(items)} weighted criteria built",
            bullets=bullets,
            raw={"criteria": items[:7]},
        )
