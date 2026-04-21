"""
Blind judging pipeline.
Anonymizes responses, sends to multiple AI judges, collects scores.
"""

import json
import random
import re

import httpx

from synthesis.evaluation.rubric import build_judge_system, build_judge_prompt
from shared.providers.base import make_httpx_timeout


# Patterns that reveal source identity
_STRIP_PATTERNS = [
    r"(?i)(GPT-?4[o\-a-z]*|GPT-?5[o\-a-z]*|ChatGPT|OpenAI)",
    r"(?i)(Claude[\s\-]?[A-Za-z0-9.]*|Anthropic|Sonnet|Opus|Haiku)",
    r"(?i)(Gemini[\s\-]?[0-9.a-z]*|Google\s?AI|Bard|PaLM)",
    r"(?i)(DeepSeek[\s\-]?[A-Za-z0-9]*|deep\s?seek)",
    r"(?i)(Grok[\s\-]?[0-9.]*|xAI|X\.AI)",
    r"(?i)I am an? (AI|language model|assistant)",
    r"(?i)As an? AI (model|assistant|language model)",
    r"(?i)(multi-?AI|orchestrat|synthesiz)",  # could reveal our app
]


def anonymize_response(text: str) -> str:
    """Strip model/vendor references from a response."""
    result = text
    for pattern in _STRIP_PATTERNS:
        result = re.sub(pattern, "[AI Model]", result)
    return result


def anonymize_responses(outputs: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """Anonymize and shuffle responses.

    Args:
        outputs: list of {"system": ..., "final_output": ...}

    Returns:
        (anonymized, key_map)
        anonymized: {"Response A": "...", "Response B": "...", ...}
        key_map: {"Response A": "orchestrator", "Response B": "standalone_openai", ...}
    """
    labels = [chr(65 + i) for i in range(len(outputs))]  # A, B, C, D...

    # Shuffle to prevent position bias
    indices = list(range(len(outputs)))
    random.shuffle(indices)

    anonymized = {}
    key_map = {}
    for label, idx in zip(labels, indices):
        resp_label = f"Response {label}"
        raw = outputs[idx].get("final_output", "")
        anonymized[resp_label] = anonymize_response(raw)
        key_map[resp_label] = outputs[idx].get("system", "unknown")

    return anonymized, key_map


# Judge model configs
JUDGE_MODELS = {
    "judge_openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o",
        "env_key": "openai_api_key",
        "header_fn": lambda key: {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        "body_fn": lambda model, system, prompt: {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "max_tokens": 4096, "temperature": 0.3,
            "response_format": {"type": "json_object"},
        },
        "extract_fn": lambda data: data["choices"][0]["message"]["content"],
    },
    "judge_anthropic": {
        "url": "https://api.anthropic.com/v1/messages",
        "model": "claude-sonnet-4-6",
        "env_key": "anthropic_api_key",
        "header_fn": lambda key: {
            "x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json",
        },
        "body_fn": lambda model, system, prompt: {
            "model": model, "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        },
        "extract_fn": lambda data: data["content"][0]["text"],
    },
    "judge_google": {
        "url_fn": lambda model, key: (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{model}:generateContent?key={key}"
        ),
        "model": "gemini-2.5-flash",
        "env_key": "google_api_key",
        "header_fn": lambda key: {"Content-Type": "application/json"},
        "body_fn": lambda model, system, prompt: {
            "contents": [{"role": "user", "parts": [{"text": system + "\n\n" + prompt}]}],
            "generationConfig": {"maxOutputTokens": 4096, "temperature": 0.3},
        },
        "extract_fn": lambda data: data["candidates"][0]["content"]["parts"][0]["text"],
    },
}


async def run_judge(
    judge_name: str,
    api_key: str,
    prompt_text: str,
    anonymized_responses: dict[str, str],
    timeout: int = 300,
    commercial: bool = False,
    model_override: str | None = None,
) -> dict:
    """Run a single judge evaluation.

    Args:
        commercial: use commercial rubric (Round 3+)
        model_override: force a specific model (for cost control)
    Returns parsed JSON scores or error dict.
    """
    config = JUDGE_MODELS.get(judge_name)
    if not config:
        return {"error": f"Unknown judge: {judge_name}"}

    system = build_judge_system(commercial=commercial)
    user_prompt = build_judge_prompt(prompt_text, anonymized_responses)
    model = model_override or config["model"]

    if "url_fn" in config:
        url = config["url_fn"](model, api_key)
    else:
        url = config["url"]

    headers = config["header_fn"](api_key)
    body = config["body_fn"](model, system, user_prompt)
    ht = make_httpx_timeout(timeout)

    try:
        async with httpx.AsyncClient(timeout=ht) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            raw_text = config["extract_fn"](data)

            # Parse JSON from response (may be wrapped in markdown)
            json_match = re.search(r'\{[\s\S]*\}', raw_text)
            if json_match:
                return json.loads(json_match.group())
            return {"error": "Judge returned no valid JSON", "raw": raw_text[:500]}

    except Exception as e:
        return {"error": str(e)[:200], "judge": judge_name}
