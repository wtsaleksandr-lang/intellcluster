"""Pragmatist Agent — execution, cost, reversibility, what actually ships."""

from __future__ import annotations

import json
from typing import Any

from ..base import Agent
from ..types import AgentOutput


class PragmatistAgent(Agent):
    name = "pragmatist"
    tier = "nuanced"
    temperature = 0.3

    system_prompt = """You are the Pragmatist Agent on an AI advisory council.

Your role: evaluate options through the lens of EXECUTION REALITY —
simplicity, cost, time-to-first-value, reversibility, opportunity cost,
and whether this user can plausibly pull it off given the context.

Your output is ONE of several perspectives the council will combine. You
care about what the user actually has to do next week, not abstract
optimality.

TASK:
  1. Score each option 0.0 - 10.0 on each criterion from a PRACTICAL
     perspective: penalize complexity, favour reversibility and clear
     next steps.
  2. Pick the option that's MOST EXECUTABLE (not best — most executable).
     That's your recommended_option.
  3. Produce:
     - reversibility    per option: "one_way" | "hard_to_unwind" |
                                     "mostly_reversible" | "fully_reversible"
     - reverse_cost     per option: short phrase (e.g. "1 quarter of ops")
     - opportunity_cost of the leading recommendation: what the user gives
                        up by doing this
     - immediate_next_step: the single concrete action in the next 48 hours
     - action_ladder: 3-5 concrete steps in order

Respond ONLY with JSON:

{
  "recommended_option": "string",
  "argument": "2-4 sentences — why this is the executable choice",
  "scores": [
    {
      "option": "string",
      "dimension_scores": {"criterion": 0.0-10.0, ...},
      "overall": 0.0-10.0,
      "strengths": ["string", ...],
      "weaknesses": ["string", ...],
      "reversibility": "one_way|hard_to_unwind|mostly_reversible|fully_reversible",
      "reverse_cost": "string"
    }
  ],
  "opportunity_cost": "one sentence",
  "immediate_next_step": "one sentence — do this in 48h",
  "action_ladder": ["step 1", "step 2", "step 3"]
}
"""

    def build_user(self, *, session, **_) -> str:
        intake = session.intake
        options = (intake.options if intake else []) or []
        criteria = [
            {"name": c.name, "weight": c.weight, "rationale": c.rationale}
            for c in session.criteria
        ]
        payload = {
            "advisory_question": intake.advisory_question if intake else session.raw_input,
            "options": options,
            "user_goal": intake.user_goal if intake else "",
            "timeline": intake.timeline if intake else None,
            "budget": intake.budget if intake else None,
            "constraints": intake.constraints if intake else [],
            "criteria": criteria,
        }
        return (
            "Advisory context. Evaluate from an execution-reality lens:\n\n"
            f"{json.dumps(payload, indent=2)}\n\n"
            "Produce the JSON practical analysis now."
        )

    def parse(self, data: dict[str, Any], **_) -> AgentOutput:
        rec = data.get("recommended_option") or ""
        arg = data.get("argument") or ""
        next_step = data.get("immediate_next_step") or ""
        ladder = data.get("action_ladder") or []
        bullets = []
        if arg:
            bullets.append(arg)
        if next_step:
            bullets.append(f"Next 48h: {next_step}")
        return AgentOutput(
            agent=self.name,
            status="ok",
            summary=f"Pragmatist: {rec}" if rec else "Pragmatist output",
            bullets=bullets,
            recommended_option=rec,
            raw={**data, "action_ladder": ladder[:5]},
        )
