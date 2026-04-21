"""
Benchmark evaluator — sends Decision Tool outputs to independent AI judges for quality grading.
Ported pattern from ai-orchestrator evaluation/judges/blind_judge.py.
"""

import json
import os
import re
import httpx

from phronesis.benchmark.rubric import build_eval_system, build_eval_prompt, DIMENSIONS
from shared.providers import get_api_key
from shared.providers.base import make_httpx_timeout


# Judge configs for benchmark evaluation
EVAL_JUDGES = {
    "eval_openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o",
        "provider": "openai",
        "header_fn": lambda key: {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        "body_fn": lambda model, system, prompt: {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "max_tokens": 600, "temperature": 0.2,
            "response_format": {"type": "json_object"},
        },
        "extract_fn": lambda data: data["choices"][0]["message"]["content"],
    },
    "eval_anthropic": {
        "url": "https://api.anthropic.com/v1/messages",
        "model": "claude-sonnet-4-6",
        "provider": "anthropic",
        "header_fn": lambda key: {"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
        "body_fn": lambda model, system, prompt: {
            "model": model, "max_tokens": 600,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        },
        "extract_fn": lambda data: data["content"][0]["text"],
    },
    "eval_google": {
        "url_fn": lambda model, key: f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        "model": "gemini-2.5-flash",
        "provider": "google",
        "header_fn": lambda key: {"Content-Type": "application/json"},
        "body_fn": lambda model, system, prompt: {
            "contents": [{"role": "user", "parts": [{"text": system + "\n\n" + prompt}]}],
            "generationConfig": {"maxOutputTokens": 600, "temperature": 0.2},
        },
        "extract_fn": lambda data: data["candidates"][0]["content"]["parts"][0]["text"],
    },
}


async def evaluate_single(
    prompt_data: dict,
    tool_output: dict,
    max_judges: int = 3,
) -> list[dict]:
    """Run benchmark evaluator judges on a single Decision Tool output."""

    system = build_eval_system()
    user_prompt = build_eval_prompt(prompt_data, tool_output)

    results = []
    for judge_name, config in EVAL_JUDGES.items():
        if len(results) >= max_judges:
            break

        api_key = get_api_key(config["provider"])
        if not api_key:
            continue

        if "url_fn" in config:
            url = config["url_fn"](config["model"], api_key)
        else:
            url = config["url"]

        headers = config["header_fn"](api_key)
        body = config["body_fn"](config["model"], system, user_prompt)
        ht = make_httpx_timeout(300)

        try:
            async with httpx.AsyncClient(timeout=ht) as client:
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                raw_text = config["extract_fn"](resp.json())

                json_match = re.search(r'\{[\s\S]*\}', raw_text)
                if json_match:
                    parsed = json.loads(json_match.group())
                    parsed["judge"] = judge_name
                    results.append(parsed)
                else:
                    results.append({"error": "No valid JSON", "judge": judge_name})
        except Exception as e:
            results.append({"error": str(e)[:200], "judge": judge_name})

    return results


def aggregate_eval(eval_results: list[dict]) -> dict:
    """Aggregate evaluator scores for a single prompt."""
    dim_scores = {d["name"]: [] for d in DIMENSIONS}
    overall_scores = []
    verdicts = []

    for result in eval_results:
        if "error" in result:
            continue
        scores = result.get("scores", {})
        for dim in DIMENSIONS:
            val = scores.get(dim["name"])
            if isinstance(val, (int, float)):
                dim_scores[dim["name"]].append(val)
        overall = result.get("overall")
        if isinstance(overall, (int, float)):
            overall_scores.append(overall)
        verdict = result.get("verdict", "")
        if verdict:
            verdicts.append(verdict)

    avg_scores = {}
    for dim_name, scores in dim_scores.items():
        avg_scores[dim_name] = round(sum(scores) / len(scores), 2) if scores else 0

    avg_overall = round(sum(overall_scores) / len(overall_scores), 2) if overall_scores else 0

    return {
        "avg_scores": avg_scores,
        "avg_overall": avg_overall,
        "eval_count": len([r for r in eval_results if "error" not in r]),
        "verdicts": verdicts,
    }
