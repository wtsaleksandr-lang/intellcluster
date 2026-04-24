"""Skeptic / Red-Team Agent — argues against the leading option, finds failure modes."""

from __future__ import annotations

import json
from typing import Any

from ..base import Agent
from ..types import AgentOutput


class SkepticAgent(Agent):
    name = "skeptic"
    tier = "nuanced"
    temperature = 0.4

    system_prompt = """You are the Skeptic / Red-Team Agent on an AI advisory
council. Your role: stress-test the leading recommendation and surface
failure modes the Optimizer might have glossed over.

Your output is ONE of several perspectives the council will combine. Be
direct and specific. Do not hedge into vague caution — name concrete
conditions under which each option fails.

TASK:
  1. Score each option 0.0 - 10.0 on each criterion from a RISK-WEIGHTED
     perspective. Penalize options with asymmetric downside, fragile
     assumptions, irreversibility under bad outcomes.
  2. Pick the option that's SAFEST (not best — safest). That's your
     recommended_option.
  3. Produce a pre-mortem: 2-3 plausible failure scenarios for the
     Optimizer's likely winner, each with:
         - probability: 0.0-1.0 rough estimate
         - severity:    1-5 (5 = worst)
         - trigger:     specific condition that would cause it
  4. Identify the single strongest argument AGAINST the Optimizer's lean.

Respond ONLY with JSON:

{
  "recommended_option": "string",
  "argument": "2-4 sentences — why the Optimizer might be wrong",
  "scores": [
    {
      "option": "string",
      "dimension_scores": {"criterion": 0.0-10.0, ...},
      "overall": 0.0-10.0,
      "strengths": ["string", ...],
      "weaknesses": ["string", ...]
    }
  ],
  "pre_mortem": [
    {
      "scenario": "string — one sentence",
      "probability": 0.0-1.0,
      "severity": 1-5,
      "trigger": "specific condition"
    }
  ],
  "single_strongest_counter": "one sentence"
}
"""

    def build_user(self, *, session, optimizer_lean: str | None = None, **_) -> str:
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
            "criteria": criteria,
            "timeline": intake.timeline if intake else None,
            "risk_tolerance": intake.risk_tolerance if intake else None,
            "optimizer_lean": optimizer_lean,
        }
        return (
            "Advisory context. Stress-test the leading recommendation:\n\n"
            f"{json.dumps(payload, indent=2)}\n\n"
            "Run the red-team pass. Return JSON."
        )

    def parse(self, data: dict[str, Any], **_) -> AgentOutput:
        rec = data.get("recommended_option") or ""
        arg = data.get("argument") or ""
        risks = [
            s.get("scenario", "")
            for s in (data.get("pre_mortem") or [])
            if s.get("scenario")
        ][:3]
        counter = data.get("single_strongest_counter")
        if counter:
            risks.insert(0, f"Counter-argument: {counter}")
        return AgentOutput(
            agent=self.name,
            status="ok",
            summary=f"Skeptic: {rec}" if rec else "Skeptic output",
            bullets=[arg] if arg else [],
            recommended_option=rec,
            risks=risks,
            raw=data,
        )
