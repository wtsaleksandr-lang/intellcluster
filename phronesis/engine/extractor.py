"""
Smart input extractor — parses a natural language decision description
into structured options, criteria, and weights using AI.
"""

import json
import os
import re

import httpx

from shared.providers import get_api_key


EXTRACT_SYSTEM = """You extract structured decision data from natural language.

Given a user's decision description, extract:
1. question: the core decision question (1 sentence)
2. options: list of distinct options being compared (2-10)
3. criteria: list of evaluation criteria with weights (1-10)

If the user mentions priorities, budget, timeline, or constraints, turn those into weighted criteria.
If criteria are not explicit, infer 2-3 reasonable ones from context.
Weights: 1=low priority, 10=critical.

Respond in JSON ONLY:
{
  "question": "Which X should I choose?",
  "options": ["Option A", "Option B"],
  "criteria": [{"name": "Cost", "weight": 8}, {"name": "Quality", "weight": 7}]
}"""

SUGGEST_SYSTEM = """Given a partial decision description, suggest 2-4 short refinement chips the user could add.
Each chip is a brief phrase that would improve the decision analysis.
Focus on missing context: budget, timeline, priorities, constraints, location, team size, etc.
Only suggest what's actually relevant to the topic.

Respond in JSON ONLY:
{"chips": ["Add budget range", "Include timeline"]}"""


async def extract_decision(text: str) -> dict | None:
    """Extract structured decision from natural language. Returns dict or None on failure."""
    api_key = get_api_key("openai") or get_api_key("anthropic")
    if not api_key:
        return None

    # Try OpenAI first (fastest for JSON extraction)
    openai_key = get_api_key("openai")
    if openai_key:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": EXTRACT_SYSTEM},
                            {"role": "user", "content": text},
                        ],
                        "max_tokens": 800,
                        "temperature": 0.2,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                return json.loads(content)
        except Exception as e:
            print(f"[extractor] OpenAI extract failed: {type(e).__name__}: {e}")

    # Fallback to Anthropic
    anthropic_key = get_api_key("anthropic")
    if anthropic_key:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": anthropic_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 800,
                        "system": EXTRACT_SYSTEM,
                        "messages": [{"role": "user", "content": text}],
                    },
                )
                resp.raise_for_status()
                raw = resp.json()["content"][0]["text"]
                match = re.search(r'\{[\s\S]*\}', raw)
                if match:
                    return json.loads(match.group())
        except Exception as e:
            print(f"[extractor] Anthropic extract failed: {type(e).__name__}: {e}")

    return None


async def suggest_chips(text: str) -> list[str]:
    """Suggest refinement chips for a partial decision description."""
    if len(text.strip()) < 10:
        return []

    openai_key = get_api_key("openai")
    if not openai_key:
        return []

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": SUGGEST_SYSTEM},
                        {"role": "user", "content": text},
                    ],
                    "max_tokens": 150,
                    "temperature": 0.3,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
            return data.get("chips", [])[:4]
    except Exception:
        return []
