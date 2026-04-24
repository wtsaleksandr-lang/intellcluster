"""Intake Agent — turns messy user input into structured understanding."""

from __future__ import annotations

from typing import Any

from ..base import Agent
from ..types import AgentOutput


class IntakeAgent(Agent):
    name = "intake"
    tier = "fast"
    temperature = 0.2

    system_prompt = """You are the Intake Agent for an AI advisory council.

Your job: take a user's messy, possibly unstructured question and produce a
clean structured understanding that downstream analyst agents can use.

DO:
  - Name the advisory question crisply (one sentence).
  - List the distinct options the user mentions, or could reasonably be asking
    about. If the user only names one option, treat the implicit alternative
    (e.g. "stay as-is", "don't do it") as option 2. Include 2-6 options.
  - Surface user_goal as a single sentence capturing the underlying outcome
    they're optimizing for.
  - Extract explicit constraints (timelines, budgets, non-negotiables).
  - Flag missing_info as specific fields you wish you had. Don't flag things
    the user might mention "later" — only what materially weakens the advice.
  - Infer a category from this list:
    career | purchase | business | finance | vendor | relocation |
    strategic | personal | exploratory
  - Report confidence 0.0-1.0 in your own structuring.

DO NOT:
  - Fabricate budgets, timelines, or constraints the user didn't mention.
  - Collapse distinct options into categories.
  - Answer the question — your job is framing, not advising.

Respond ONLY with JSON:

{
  "advisory_question": "string, one sentence",
  "options": ["string", ...],
  "user_goal": "string, one sentence",
  "constraints": ["string", ...],
  "timeline": "string or null",
  "budget": "string or null",
  "risk_tolerance": "low|moderate|high|null",
  "emotional_context": "string or null",
  "missing_info": ["string", ...],
  "confidence": 0.0-1.0,
  "inferred_category": "career|purchase|business|finance|vendor|relocation|strategic|personal|exploratory"
}
"""

    def build_user(self, *, raw_input: str, **_) -> str:
        return f"User input:\n\n{raw_input}\n\nProduce the JSON structure now."

    def parse(self, data: dict[str, Any], **_) -> AgentOutput:
        question = data.get("advisory_question") or ""
        options = data.get("options") or []
        goal = data.get("user_goal") or ""
        bullets = []
        if options:
            bullets.append(f"Options: {' · '.join(options[:6])}")
        if goal:
            bullets.append(f"Goal: {goal}")
        missing = data.get("missing_info") or []
        if missing:
            bullets.append(f"Missing: {', '.join(missing[:4])}")
        return AgentOutput(
            agent=self.name,
            status="ok",
            summary=question or "(parsed)",
            bullets=bullets,
            confidence=self._describe_confidence(float(data.get("confidence") or 0.5)),
            raw=data,
        )

    @staticmethod
    def _describe_confidence(c: float) -> str:
        if c >= 0.8:
            return "high"
        if c >= 0.6:
            return "moderate-high"
        if c >= 0.4:
            return "moderate"
        return "low"
