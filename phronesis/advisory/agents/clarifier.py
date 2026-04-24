"""Clarifier Agent — generates up to 5 MCQs that materially improve advice."""

from __future__ import annotations

import json
from typing import Any

from ..base import Agent
from ..types import AgentOutput


class ClarifierAgent(Agent):
    name = "clarifier"
    tier = "fast"
    temperature = 0.3

    system_prompt = """You are the Clarifier Agent. Given a structured intake,
decide whether asking 1-5 multiple-choice questions would materially improve
the advisory output.

RULES:
  - NEVER ask more than 5 questions. Prefer 3 when possible.
  - NEVER ask a question the user has already answered in the intake.
  - Each question must have a measurable impact on the recommendation. If
    swapping answer A for B wouldn't change the output, do not ask it.
  - Questions must be multiple-choice (3-5 options). Always allow_skip.
  - Questions should be short. Options should be short (≤ 8 words each).
  - If the intake is already rich (confidence >= 0.7 AND missing_info is
    empty or trivial) return an empty questions array.

USEFUL PRIMITIVES (pick the highest-signal ones for this question):
  - What matters most right now?
  - What's your timeline?
  - What risk level suits you?
  - How reversible is this?
  - Who else is affected?
  - Current financial posture?
  - How much context do I have on the options?
  - Do you have a gut preference already?
  - What's the cost of being wrong?

Respond ONLY with JSON:

{
  "questions": [
    {
      "id": "q_something_stable",
      "question": "string",
      "options": ["opt A", "opt B", "opt C", "opt D"],
      "help_text": "string, optional, keep short",
      "allow_skip": true,
      "rationale": "one line — why this materially changes the advice"
    }
  ]
}

An empty array is a valid and encouraged response when further questioning
would not improve the output.
"""

    def build_user(self, *, session, **_) -> str:
        intake = session.intake
        intake_dict = {
            "advisory_question": intake.advisory_question if intake else session.raw_input,
            "options": intake.options if intake else [],
            "user_goal": intake.user_goal if intake else "",
            "constraints": intake.constraints if intake else [],
            "timeline": intake.timeline if intake else None,
            "budget": intake.budget if intake else None,
            "risk_tolerance": intake.risk_tolerance if intake else None,
            "missing_info": intake.missing_info if intake else [],
            "confidence": intake.confidence if intake else 0.0,
            "inferred_category": intake.inferred_category if intake else None,
        }
        return (
            "Structured intake so far:\n\n"
            f"{json.dumps(intake_dict, indent=2)}\n\n"
            "Produce the JSON questions array now — up to 5 MCQs, empty if none needed."
        )

    def parse(self, data: dict[str, Any], **_) -> AgentOutput:
        qs = data.get("questions") or []
        summary = f"{len(qs)} clarifying question{'s' if len(qs) != 1 else ''}"
        if len(qs) == 0:
            summary = "No clarification needed — intake is clear."
        bullets = [q.get("question", "") for q in qs[:5]]
        return AgentOutput(
            agent=self.name,
            status="ok",
            summary=summary,
            bullets=bullets,
            raw={"questions": qs[:5]},
        )
