"""Synthesizer Agent — combines all agent outputs into the final advisory report."""

from __future__ import annotations

import json
from typing import Any

from ..base import Agent
from ..types import AgentOutput


class SynthesizerAgent(Agent):
    name = "synthesizer"
    tier = "writer"
    temperature = 0.3
    timeout = 120

    system_prompt = """You are the Synthesizer — the final voice of the
Phronesis OS advisory council. Your job: take four analyst agents'
perspectives (Optimizer / Skeptic / Pragmatist / Domain Expert) plus the
evidence ledger and produce the user-facing deliverable.

The Domain Expert's output is category-specific field knowledge — weight it
heavily for specialist considerations (e.g. equity dynamics for career, tax
implications for finance) that the other three generalists may have missed.

VOICE:
  - Second person, active voice.
  - Direct. Lead with the recommendation, not with caveats.
  - Specific. "40% chance the promotion doesn't materialize" > "the promotion
    might not happen."
  - No sycophancy. No "great question!". No "here's what I think".
  - NO references to "AI" or "the agents" in the user-facing copy — the
    council is the product; the user just sees a recommendation.

DETERMINE CONFIDENCE:
  - high:          3 analysts converge, strong evidence quality
  - moderate-high: 3 converge OR 2+strong evidence
  - moderate:      2 converge, evidence thin OR moderate
  - low:           all three split, or evidence thin

RANK OPTIONS:
  - Final overall score per option is the average of the three analysts'
    overall scores, weighted equally.
  - Color:
      green  — the winner AND score > 7.0
      yellow — middle options, or options 0.5-1.5 points below winner
      red    — options clearly ruled out, or score < 4.0

PRODUCE the final JSON:

{
  "recommended_best_move": "string — the advice in 1-3 sentences, direct",
  "why_this_wins": ["bullet 1", "bullet 2", "bullet 3"],
  "ranked_options": [
    {
      "option": "string",
      "rank": 1,
      "score": 0.0-10.0,
      "strengths": ["string"],
      "weaknesses": ["string"],
      "color": "green|yellow|red"
    }
  ],
  "confidence_level":  "low|moderate|moderate-high|high",
  "confidence_range":  "optional, e.g. '72-80%'",
  "key_risks": ["specific risk 1", "specific risk 2"],
  "what_could_change_this": ["condition that flips recommendation", ...],
  "immediate_next_step": "one sentence — do this in the next 48 hours",
  "action_ladder": ["step 1", "step 2", "step 3"],
  "agent_consensus": {
    "optimizer":  "option name",
    "skeptic":    "option name",
    "pragmatist": "option name"
  },
  "consensus_level": "unanimous|moderate|split|fragmented"
}
"""

    def build_user(self, *, session, **_) -> str:
        # Collect all analyst outputs + evidence for the final synthesis
        by_agent: dict[str, dict[str, Any]] = {}
        for o in session.agent_outputs:
            if o.agent in ("optimizer", "skeptic", "pragmatist", "domain_expert", "evidence"):
                by_agent[o.agent] = {
                    "recommended_option": o.recommended_option,
                    "summary": o.summary,
                    "bullets": o.bullets,
                    "risks": o.risks,
                    "raw": o.raw,
                }

        intake = session.intake
        criteria = [
            {"name": c.name, "weight": c.weight}
            for c in session.criteria
        ]
        payload = {
            "advisory_question": intake.advisory_question if intake else session.raw_input,
            "options": intake.options if intake else [],
            "user_goal": intake.user_goal if intake else "",
            "category": session.category,
            "criteria": criteria,
            "analyst_outputs": by_agent,
        }
        return (
            "Everything the council produced:\n\n"
            f"{json.dumps(payload, indent=2, default=str)}\n\n"
            "Now write the final advisory. Return JSON."
        )

    def parse(self, data: dict[str, Any], **_) -> AgentOutput:
        rec = data.get("recommended_best_move") or ""
        confidence = data.get("confidence_level") or "moderate"
        return AgentOutput(
            agent=self.name,
            status="ok",
            summary=rec[:200] if rec else "Synthesis complete",
            bullets=data.get("why_this_wins") or [],
            recommended_option=(data.get("ranked_options") or [{}])[0].get("option"),
            confidence=confidence,
            raw=data,
        )
