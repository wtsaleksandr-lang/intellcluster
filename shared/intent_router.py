"""
Intent Router — classifies user input as belonging to Phronesis or Synthesis.

Used to offer smart cross-tool handoffs:
- If a user pastes "Should I buy X or Y?" into Synthesis, offer handoff to Phronesis.
- If a user pastes "What's the state of X market in 2026?" into Phronesis, offer handoff to Synthesis.

Uses a fast, cheap classifier (gpt-4o-mini) with deterministic fallback heuristics.
"""

import json
import re
from typing import Literal

import httpx

from shared.providers import get_api_key


IntentTool = Literal["phronesis", "synthesis", "ambiguous"]


# Heuristic patterns — fast deterministic classification for obvious cases
PHRONESIS_SIGNALS = [
    r"\b(compare|vs\.?|versus|which is better|should i choose|should i buy|which one)\b",
    r"\b(option a|option b|choose between)\b",
    r"\brank(ing)?\b",
    r"\bcriteria\b.*\b(weight|priorit)",
    r"\bwhich (tool|platform|product|vendor|service) (should|would)\b",
]

SYNTHESIS_SIGNALS = [
    r"\bresearch\b",
    r"\b(what is|what are|explain|describe|tell me about)\b",
    r"\b(analyze|analyse) (the|this|that)\b",
    r"\b(state of|landscape of|overview of|deep dive)\b",
    r"\bmarket analysis\b",
    r"\bhow (does|do|can|to)\b",
]


def heuristic_classify(text: str) -> tuple[IntentTool, float]:
    """Fast pattern-based classification. Returns (tool, confidence 0-1)."""
    t = text.lower().strip()

    phron_hits = sum(1 for p in PHRONESIS_SIGNALS if re.search(p, t))
    synth_hits = sum(1 for p in SYNTHESIS_SIGNALS if re.search(p, t))

    # Strong Phronesis signal: has options structure (A vs B, lists with "or")
    if re.search(r"\b\w+\s+(?:vs\.?|or|versus)\s+\w+", t) and len(t) < 500:
        phron_hits += 2

    # Strong Synthesis signal: long open-ended question
    if len(t) > 300 and phron_hits == 0:
        synth_hits += 1

    if phron_hits > synth_hits and phron_hits >= 1:
        confidence = min(0.6 + (phron_hits - synth_hits) * 0.15, 0.95)
        return "phronesis", confidence
    if synth_hits > phron_hits and synth_hits >= 1:
        confidence = min(0.6 + (synth_hits - phron_hits) * 0.15, 0.95)
        return "synthesis", confidence
    return "ambiguous", 0.3


CLASSIFIER_SYSTEM = """You are an intent classifier for a research platform with two tools:

1. PHRONESIS — compares specific options and ranks them. Use when the user has 2+ named alternatives and wants to pick one. Examples: "Tesla vs Mach-E", "Should I hire senior or junior?", "Compare HubSpot, Salesforce, Pipedrive."

2. SYNTHESIS — deep multi-model research on open-ended questions. Use when the user wants analysis, explanation, or landscape overview. Examples: "What's the best pricing strategy for B2B SaaS in 2026?", "Analyze the electric vehicle market", "How does intermittent fasting work?"

Classify the user's input. Respond ONLY with JSON:
{"tool": "phronesis" | "synthesis" | "ambiguous", "confidence": 0.0-1.0, "reason": "<one sentence>"}

Rules:
- If they list 2+ specific options to compare → phronesis
- If they ask an open-ended research question → synthesis
- If truly both (e.g., "research the top 5 CRMs and help me pick one") → ambiguous
- confidence: 0.9+ only when clear, 0.5-0.8 for likely, <0.5 for unclear"""


async def ai_classify(text: str) -> dict:
    """AI-backed classification for ambiguous cases. Returns dict with tool, confidence, reason."""
    api_key = get_api_key("openai")
    if not api_key:
        # Try Anthropic
        api_key = get_api_key("anthropic")
        if not api_key:
            return {"tool": "ambiguous", "confidence": 0.3, "reason": "No AI classifier available"}
        return await _classify_anthropic(text, api_key)
    return await _classify_openai(text, api_key)


async def _classify_openai(text: str, api_key: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": CLASSIFIER_SYSTEM},
                        {"role": "user", "content": text[:1500]},
                    ],
                    "max_tokens": 120,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            tool = parsed.get("tool", "ambiguous")
            if tool not in ("phronesis", "synthesis", "ambiguous"):
                tool = "ambiguous"
            return {
                "tool": tool,
                "confidence": float(parsed.get("confidence", 0.5)),
                "reason": parsed.get("reason", "")[:200],
            }
    except Exception:
        return {"tool": "ambiguous", "confidence": 0.3, "reason": "Classification error"}


async def _classify_anthropic(text: str, api_key: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 120,
                    "system": CLASSIFIER_SYSTEM,
                    "messages": [{"role": "user", "content": text[:1500]}],
                },
            )
            resp.raise_for_status()
            raw = resp.json()["content"][0]["text"]
            match = re.search(r'\{[\s\S]*\}', raw)
            if match:
                parsed = json.loads(match.group())
                tool = parsed.get("tool", "ambiguous")
                if tool not in ("phronesis", "synthesis", "ambiguous"):
                    tool = "ambiguous"
                return {
                    "tool": tool,
                    "confidence": float(parsed.get("confidence", 0.5)),
                    "reason": parsed.get("reason", "")[:200],
                }
    except Exception:
        pass
    return {"tool": "ambiguous", "confidence": 0.3, "reason": "Classification error"}


async def classify_intent(text: str, current_tool: IntentTool | None = None) -> dict:
    """Classify user intent. Returns dict with tool, confidence, reason, should_handoff.

    Strategy:
    1. Run heuristic first (fast, free)
    2. If high confidence, return heuristic result
    3. Otherwise, use AI classifier

    should_handoff = True when:
    - current_tool is set
    - intent tool != current_tool
    - confidence >= 0.65
    """
    if not text or len(text.strip()) < 8:
        return {"tool": "ambiguous", "confidence": 0.0, "reason": "Input too short", "should_handoff": False}

    # Heuristic first
    heur_tool, heur_conf = heuristic_classify(text)
    if heur_conf >= 0.75:
        result = {"tool": heur_tool, "confidence": heur_conf, "reason": "Pattern-matched"}
    else:
        # Fall back to AI classifier for low-confidence cases
        result = await ai_classify(text)

    # Handoff decision
    should_handoff = False
    if current_tool and result["tool"] != "ambiguous" and result["tool"] != current_tool:
        if result["confidence"] >= 0.65:
            should_handoff = True

    result["should_handoff"] = should_handoff
    result["current_tool"] = current_tool
    return result
