"""
Synthesizer — reads all judge outputs + aggregated scores, writes a coherent recommendation.
Replaces the old "pick first judge explanation" approach.
"""

import json
import re
import httpx
from shared.providers import get_api_key


SYNTHESIZE_SYSTEM = """You are a senior decision advisor writing a final recommendation.

You have access to:
1. The original question
2. Scores and rankings from multiple independent analysts
3. Each analyst's individual reasoning

Your job: write a clear, decisive recommendation in 2-3 sentences.

RULES:
- State the winner and WHY it wins — be specific, not generic.
- If analysts disagreed, acknowledge the split briefly but still commit to the recommendation.
- Mention the runner-up only if it's genuinely close (within 1 point).
- Never hedge with "it depends" or "consider your needs" — the user already told us their needs.
- Never start with "Based on the analysis" or similar filler.
- Be direct. First sentence = the recommendation. Second sentence = the key reason. Optional third = what to watch out for."""


async def synthesize_recommendation(
    question: str,
    winner: str,
    ranked_options: list[dict],
    judge_explanations: list[str],
    judges_agree: bool,
    judge_count: int,
) -> str:
    """Generate a coherent recommendation by synthesizing all judge outputs."""

    # Build context for synthesizer
    rankings_text = "\n".join(
        f"  #{o['rank']} {o['option']} — score {o['score']:.1f}/10"
        for o in ranked_options[:4]
    )

    explanations_text = "\n".join(
        f"  Analyst {i+1}: {e}" for i, e in enumerate(judge_explanations[:3])
    ) if judge_explanations else "  No individual explanations available."

    agreement = "All analysts agree" if judges_agree else "Analysts disagree on the winner"

    prompt = f"""Question: {question}

Winner: {winner}
{agreement} ({judge_count} analysts evaluated)

Rankings:
{rankings_text}

Analyst reasoning:
{explanations_text}

Write your 2-3 sentence recommendation. Be direct and specific."""

    # Try OpenAI (fast, cheap)
    openai_key = get_api_key("openai")
    if openai_key:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": SYNTHESIZE_SYSTEM},
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 200,
                        "temperature": 0.3,
                    },
                )
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"].strip()
                # Clean up: remove quotes if wrapped
                if text.startswith('"') and text.endswith('"'):
                    text = text[1:-1]
                return text
        except Exception:
            pass

    # Fallback to Anthropic
    anthropic_key = get_api_key("anthropic")
    if anthropic_key:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": anthropic_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 200,
                        "system": SYNTHESIZE_SYSTEM,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                return resp.json()["content"][0]["text"].strip()
        except Exception:
            pass

    # Final fallback: use old verdict logic
    return None
