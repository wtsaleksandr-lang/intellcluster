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

    # Ask the provider for native web search. Claude executes
    # web_search_20250305 server-side, OpenAI swaps to a -search-preview
    # model, Gemini uses google_search grounding. Providers without native
    # support ignore this flag — the Agent falls back to its strict
    # anti-hallucination default behaviour (flag missing facts, don't fabricate).
    web_search = True

    system_prompt = """You are the Evidence / Assumption Agent. Given an
advisory question and its structured intake, produce a crisp ledger that
separates:

  1. facts_from_user        — things the user explicitly stated
  2. reasonable_assumptions — things not stated but reasonable to assume
                              given the context (label clearly as assumption)
  3. missing_critical       — information that, if known, would materially
                              change the recommendation
  4. external_reference     — verifiable external facts. You have native web
                              search available: use it to ground specific
                              claims (current prices, product specs, market
                              stats, recent events). When you do, include the
                              URL in the `source` field. If you cannot verify
                              a would-be reference, move it to missing_critical
                              instead of fabricating.

RULES:
  - Prefer real web search results over prior-training knowledge for anything
    that might be stale (prices, product specs, current events, regulations).
  - For every external_reference you include, put the source URL in `source`.
  - NEVER invent statistics or URLs. If search didn't return something, flag
    the unknown in missing_critical.
  - Speculation about future outcomes belongs in the Optimizer/Skeptic — not here.

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

        # Web search is OPTIONAL scaffolding. The pipeline orchestrator runs
        # the async search BEFORE calling this agent and stashes a prompt
        # fragment on session._web_search_block. When TAVILY_API_KEY isn't
        # set, the fragment stays empty and the Agent behaves as before.
        web_block = getattr(session, "_web_search_block", "") or ""

        parts = [
            f"Intake + raw user input:\n\n{json.dumps(intake_dict, indent=2)}",
        ]
        if web_block:
            parts.extend(["", web_block])
        parts.extend(["", "Produce the JSON evidence ledger now."])
        return "\n\n".join(parts)

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
