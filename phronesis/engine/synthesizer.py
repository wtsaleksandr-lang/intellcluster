"""
Synthesizer — reads all judge outputs + aggregated scores, writes a coherent recommendation.
Replaces the old "pick first judge explanation" approach.
"""

import json
import re
import httpx
from shared.providers import get_api_key


SYNTHESIZE_SYSTEM = """You are a senior decision advisor writing a final recommendation. The user has paid for an in-depth analysis — your output must read like an expert analyst's memo, not a one-line verdict.

You have access to:
1. The original question and all options/criteria
2. Scores from multiple independent analysts who evaluated each option
3. Each analyst's reasoning and any role-specific findings (failure modes, base rates, counterarguments)

Write a STRUCTURED ANALYSIS with these sections:

## Recommendation
The winning option, stated decisively in one line. No hedging.

## Why this wins
3-5 specific reasons, each with concrete numbers, base rates, or named factors. Show the math where possible (TCO calculations, expected value, ratios). DO NOT write generic statements like "lower cost and higher reliability" — write "TCO over 5 years is ~$21K vs ~$40K, a $19K gap".

## Why the alternatives lose
For each runner-up, 2-3 specific weaknesses that drove its score down. Be concrete.

## Risks and watch-outs
2-4 things that could change this recommendation, with specific monitoring criteria. Reference the analysts' identified failure modes if any.

## Confidence
A direct statement of how confident this recommendation is and why (analyst agreement, evidence quality, presence/absence of base rates).

RULES:
- Use numbers wherever possible. If the analysts cite specific costs/rates/percentages, surface them. If the input has costs/dates/quantities, do the math.
- Never write "it depends" or "consider your goals" — the user gave us their criteria; analyze against them.
- Never start with filler like "Based on the analysis" or "After careful consideration".
- Specificity beats brevity. A 600-word concrete analysis is better than a 100-word vague one.
- If the analysts' role-specific findings (failure_modes, base_rates, counterarguments) are present, integrate them — don't just summarize.

ANTI-HALLUCINATION RULES (critical):
- Every specific number you write must come from EITHER (a) the original question, (b) an analyst's reasoning, (c) a calculation you can show. If a number didn't come from one of these sources, do not invent it.
- Do NOT cite specific studies, papers, J.D. Power scores, NHTSA ratings, or named statistics unless the analyst already cited them. The analysts are not authoritative sources for facts the user didn't supply.
- When the analysts cite a number with no source, hedge it: write "analyst panel estimated ~X%" not "X% per industry data".
- For domain-specific claims (insurance rates, mortgage formulas, tax brackets, drug interactions, legal precedents, etc.), prefer flagging "no analyst surfaced authoritative data on X — confirm with [domain expert]" over inventing the number.
- Never claim consensus you don't see — "all analysts agreed X" only when judges_agree was true."""


async def synthesize_recommendation(
    question: str,
    winner: str,
    ranked_options: list[dict],
    judge_explanations: list[str],
    judges_agree: bool,
    judge_count: int,
    judge_extras: list[dict] | None = None,
    criteria: list[dict] | None = None,
) -> str:
    """Generate a structured expert analysis by synthesizing all judge outputs.

    judge_extras (v2): per-judge role-specific findings: list of dicts with keys
    like 'failure_modes', 'base_rates', 'counterarguments'. Surfaced in the
    synthesis prompt so the writer can integrate role-specific reasoning.
    """

    # Build rich context for synthesizer
    rankings_text = "\n".join(
        f"  #{o['rank']} {o['option']} — score {o['score']:.2f}/10"
        + (f" (strengths: {'; '.join(o.get('strengths', [])[:2])})" if o.get('strengths') else "")
        + (f" (weaknesses: {'; '.join(o.get('weaknesses', [])[:2])})" if o.get('weaknesses') else "")
        for o in ranked_options[:5]
    )

    explanations_text = "\n\n".join(
        f"### Analyst {i+1}\n{e}" for i, e in enumerate(judge_explanations[:5])
    ) if judge_explanations else "  No individual explanations available."

    extras_text = ""
    if judge_extras:
        sections = []
        for i, ex in enumerate(judge_extras):
            if not isinstance(ex, dict):
                continue
            bits = []
            if ex.get("failure_modes"):
                bits.append("Failure modes identified: " + "; ".join(str(x) for x in ex["failure_modes"][:5]))
            if ex.get("base_rates"):
                bits.append("Base rates cited: " + "; ".join(str(x) for x in ex["base_rates"][:5]))
            if ex.get("counterarguments"):
                bits.append("Counter-arguments: " + "; ".join(str(x) for x in ex["counterarguments"][:5]))
            if bits:
                sections.append(f"### Role-specific findings (analyst {i+1})\n" + "\n".join(bits))
        if sections:
            extras_text = "\n\n" + "\n\n".join(sections)

    criteria_text = ""
    if criteria:
        criteria_text = "\n## Stated criteria (with weights)\n" + "\n".join(
            f"- {c.get('name', '?')} (weight {c.get('weight', 5)})" for c in criteria
        )

    agreement = (
        "All analysts agreed on the winner"
        if judges_agree
        else f"Analysts split on the winner — disagreement is itself a signal of difficulty"
    )

    prompt = f"""## Original question
{question}
{criteria_text}

## Analyst conclusion
Winner: {winner}
{agreement} ({judge_count} analysts evaluated)

## Rankings (highest to lowest score)
{rankings_text}

## Analyst reasoning (one paragraph per analyst, in their own words)

{explanations_text}{extras_text}

Now write the structured expert analysis. Use the section headings (Recommendation, Why this wins, Why the alternatives lose, Risks and watch-outs, Confidence). Integrate the analysts' specific findings; cite numbers where the analysts cited them; do the math where the question gives you raw figures."""

    # Synthesizer is the face of the recommendation — use Sonnet for prose
    # quality (the eval showed Sonnet writes the most actionable analysis;
    # gpt-4o-mini was producing committee-summary-flavored output that judges
    # ranked far below solo Sonnet). One call per run; cost is minor.
    anthropic_key = get_api_key("anthropic")
    if anthropic_key:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": anthropic_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                    json={
                        "model": "claude-sonnet-4-6",
                        "max_tokens": 1500,
                        "system": SYNTHESIZE_SYSTEM,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                text = "".join(b.get("text", "") for b in resp.json().get("content", []) if b.get("type") == "text")
                return text.strip()
        except Exception as e:
            print(f"[synthesizer] Anthropic synth failed: {type(e).__name__}: {e}")

    # Fallback: gpt-4o (not mini — this output is user-facing prose)
    openai_key = get_api_key("openai")
    if openai_key:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                    json={
                        "model": "gpt-4o",
                        "messages": [
                            {"role": "system", "content": SYNTHESIZE_SYSTEM},
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 1500,
                        "temperature": 0.3,
                    },
                )
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"].strip()
                if text.startswith('"') and text.endswith('"'):
                    text = text[1:-1]
                return text
        except Exception as e:
            print(f"[synthesizer] OpenAI synth failed: {type(e).__name__}: {e}")

    # Final fallback: use old verdict logic
    return None
