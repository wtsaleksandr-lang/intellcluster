"""Evidence / Assumption Agent — separates what we know from what we don't."""

from __future__ import annotations

import json
from typing import Any

from ..base import Agent
from ..types import AgentOutput


class EvidenceAgent(Agent):
    name = "evidence"
    tier = "balanced"
    temperature = 0.2

    system_prompt = """You are the Evidence / Assumption Agent. Given an
advisory question and its structured intake, produce a crisp ledger that
separates:

  1. facts_from_user        — things the user explicitly stated
  2. reasonable_assumptions — things not stated but reasonable to assume
                              given the context (label clearly as assumption)
  3. missing_critical       — information that, if known, would materially
                              change the recommendation
  4. external_reference     — well-known prior knowledge (e.g. "Apple's M3
                              chip released late 2024") — ONLY include if you
                              are >95% confident and it's directly relevant.
                              NEVER invent statistics. NEVER cite sources
                              you can't verify from training.

DO NOT:
  - Fabricate statistics, prices, success rates, market data, or URLs.
  - Cite web pages, papers, or reports by title unless you are certain.
  - Speculate about future outcomes — that's the Optimizer/Skeptic's job.

If you would need to fabricate something to answer usefully, put the claim
in missing_critical instead.

Also produce evidence_quality, a one-word verdict: strong | moderate | thin.

Respond ONLY with JSON:

{
  "facts_from_user":        [{"claim": "string", "confidence": "high"}],
  "reasonable_assumptions": [{"claim": "string", "confidence": "medium"}],
  "missing_critical":       [{"claim": "string", "confidence": "low"}],
  "external_reference":     [{"claim": "string", "confidence": "high",
                              "source": "well-known general knowledge"}],
  "evidence_quality":       "strong|moderate|thin"
}
"""

    def build_user(self, *, session, **_) -> str:
        intake = session.intake
        intake_dict = {
            "advisory_question": intake.advisory_question if intake else "",
            "options": intake.options if intake else [],
            "constraints": intake.constraints if intake else [],
            "timeline": intake.timeline if intake else None,
            "budget": intake.budget if intake else None,
            "raw_user_input": session.raw_input,
        }
        return (
            f"Intake + raw user input:\n\n"
            f"{json.dumps(intake_dict, indent=2)}\n\n"
            "Produce the JSON evidence ledger now."
        )

    def parse(self, data: dict[str, Any], **_) -> AgentOutput:
        facts = data.get("facts_from_user") or []
        assumptions = data.get("reasonable_assumptions") or []
        missing = data.get("missing_critical") or []
        quality = (data.get("evidence_quality") or "moderate").lower()

        bullets: list[str] = []
        if facts:
            bullets.append(f"{len(facts)} facts from user")
        if assumptions:
            bullets.append(f"{len(assumptions)} reasonable assumptions")
        if missing:
            bullets.append(f"{len(missing)} missing critical pieces")

        return AgentOutput(
            agent=self.name,
            status="ok",
            summary=f"Evidence quality: {quality}",
            bullets=bullets,
            raw=data,
            confidence=quality,
        )
