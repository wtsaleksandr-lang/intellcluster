"""Optimizer Agent — argues for the option with the highest upside."""

from __future__ import annotations

import json
from typing import Any

from ..base import Agent
from ..types import AgentOutput


class OptimizerAgent(Agent):
    name = "optimizer"
    tier = "nuanced"
    temperature = 0.5

    system_prompt = """You are the Optimizer Agent on an AI advisory council.

Your role: argue for the option that maximises UPSIDE, weighted by the
criteria in the scoring rubric. You lean into potential, but not recklessly
— a 5% chance of tenfold upside is not automatically better than a 90%
chance of 2x.

Your output is ONE of several perspectives the council will combine. Be
confident in your lean; other agents will push back.

TASK:
  1. Score each option 0.0 - 10.0 on each criterion, from an upside-
     weighted perspective. Favor optionality, compounding, and expected
     value.
  2. Identify a recommended_option and a one-paragraph argument.
  3. Surface the top 2-3 upsides and the single biggest upside risk
     (a downside that would tank the upside case).

Respond ONLY with JSON:

{
  "recommended_option": "string",
  "argument": "2-4 sentences",
  "scores": [
    {
      "option": "string",
      "dimension_scores": {"criterion name": 0.0-10.0, ...},
      "overall": 0.0-10.0,
      "strengths": ["string", ...],
      "weaknesses": ["string", ...]
    }
  ],
  "biggest_upside_risk": "one sentence"
}
"""

    def build_user(self, *, session, **_) -> str:
        intake = session.intake
        options = (intake.options if intake else []) or []
        criteria = [
            {"name": c.name, "weight": c.weight, "rationale": c.rationale}
            for c in session.criteria
        ]
        evidence_raw: dict[str, Any] = {}
        for o in session.agent_outputs:
            if o.agent == "evidence" and o.raw:
                evidence_raw = o.raw
                break

        payload = {
            "advisory_question": intake.advisory_question if intake else session.raw_input,
            "options": options,
            "user_goal": intake.user_goal if intake else "",
            "timeline": intake.timeline if intake else None,
            "risk_tolerance": intake.risk_tolerance if intake else None,
            "criteria": criteria,
            "evidence": evidence_raw,
        }
        return (
            "Advisory context:\n\n"
            f"{json.dumps(payload, indent=2)}\n\n"
            "Argue the upside case. Score each option. Return JSON."
        )

    def parse(self, data: dict[str, Any], **_) -> AgentOutput:
        rec = data.get("recommended_option") or ""
        arg = data.get("argument") or ""
        return AgentOutput(
            agent=self.name,
            status="ok",
            summary=f"Optimizer: {rec}" if rec else "Optimizer output",
            bullets=[arg] if arg else [],
            recommended_option=rec,
            risks=[data.get("biggest_upside_risk")] if data.get("biggest_upside_risk") else [],
            raw=data,
        )
