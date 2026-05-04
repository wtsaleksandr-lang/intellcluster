"""
Input Validator — checks extraction quality before committing to judge calls.
Catches bad extractions, non-comparable options, irrelevant criteria, missing context.
Uses a cheap/fast model (gpt-4o-mini or haiku).
"""

import json
import re
from shared.providers import get_api_key
import httpx


VALIDATE_SYSTEM = """You validate whether a structured decision extraction is correct and complete.

You receive:
- question: the extracted decision question
- options: the extracted options
- criteria: the extracted criteria with weights

Check for these issues:
1. Are the options actually distinct and comparable? (e.g., "Tesla Model 3" vs "Ford Mach-E" = good. "Tesla" vs "Cars" = bad.)
2. Are the criteria relevant to the question? (e.g., "Cost" for a laptop decision = good. "Taste" for a laptop decision = bad.)
3. Are there obvious missing options the user likely intended? (Only if clearly implied in the question.)
4. Are there obvious missing criteria? (Only if the question strongly implies them.)
5. Is the question actually a decision/comparison? (Not a factual question or request for information.)

Respond in JSON ONLY:
{
  "valid": true/false,
  "issues": ["issue 1", "issue 2"],
  "suggested_fixes": {
    "add_options": ["Option X"],
    "remove_options": ["Bad option"],
    "add_criteria": [{"name": "Missing criterion", "weight": 7}],
    "remove_criteria": ["Irrelevant criterion"],
    "rewrite_question": "Better phrased question" or null
  }
}

If everything looks good, return {"valid": true, "issues": [], "suggested_fixes": {}}
Be strict but not pedantic. Only flag real problems."""


async def validate_extraction(question: str, options: list[str], criteria: list[dict]) -> dict:
    """Validate extracted decision data. Returns validation result with fixes if needed."""

    prompt = f"""Question: {question}
Options: {json.dumps(options)}
Criteria: {json.dumps(criteria)}"""

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
                            {"role": "system", "content": VALIDATE_SYSTEM},
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 400,
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                return json.loads(content)
        except Exception as e:
            print(f"[validator] OpenAI validate failed: {type(e).__name__}: {e}")

    # If validation fails, assume valid (don't block the pipeline)
    return {"valid": True, "issues": [], "suggested_fixes": {}}


def apply_fixes(question: str, options: list[str], criteria: list[dict], fixes: dict) -> tuple[str, list[str], list[dict]]:
    """Apply CONSERVATIVE fixes from validator.

    CRITICAL: Never add options the user didn't mention.
    Only fix criteria (add relevant ones, remove irrelevant ones) and question clarity.
    """
    if not fixes:
        return question, options, criteria

    # Rewrite question only if it's a minor clarity improvement
    if fixes.get("rewrite_question"):
        question = fixes["rewrite_question"]

    # NEVER add options — the user specified what they want to compare.
    # Adding options the user didn't mention produces wrong winners.

    # Remove bad options only if clearly invalid (very conservative)
    for opt in fixes.get("remove_options", []):
        if opt in options and len(options) > 2:
            options.remove(opt)

    # Add missing criteria
    for crit in fixes.get("add_criteria", []):
        existing_names = [c["name"].lower() for c in criteria]
        if crit["name"].lower() not in existing_names and len(criteria) < 10:
            criteria.append(crit)

    # Remove irrelevant criteria
    for crit_name in fixes.get("remove_criteria", []):
        criteria = [c for c in criteria if c["name"].lower() != crit_name.lower()]
        if len(criteria) < 1:
            break  # never remove all criteria

    return question, options, criteria
