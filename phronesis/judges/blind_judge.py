"""
Blind judging pipeline for decision options.
Anonymizes and shuffles options, sends to multiple AI judges, collects scores.
Ported from ai-orchestrator evaluation/judges/blind_judge.py — adapted for user options.
"""

import json
import random
import re

import httpx

from phronesis.judges.rubric import build_judge_system, build_judge_prompt
from shared.providers.base import make_httpx_timeout


def anonymize_options(options: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """Anonymize and shuffle user options to prevent position bias.

    Args:
        options: list of option descriptions

    Returns:
        (anonymized, key_map)
        anonymized: {"Option A": "description...", "Option B": "...", ...}
        key_map: {"Option A": "original option text", ...}
    """
    labels = [chr(65 + i) for i in range(len(options))]  # A, B, C, D...

    # Shuffle to prevent position bias
    indices = list(range(len(options)))
    random.shuffle(indices)

    anonymized = {}
    key_map = {}
    for label, idx in zip(labels, indices):
        opt_label = f"Option {label}"
        anonymized[opt_label] = options[idx]
        key_map[opt_label] = options[idx]

    return anonymized, key_map


# Judge model configs — same pattern as ai-orchestrator
# Judge JSON output: 3 options × ~6 dimensions × rationale text fits in
# ~2500 tokens in practice; 3000 gives headroom against truncation on
# long rationales without permitting the rare 4096-token ramble. Setting
# too low truncates JSON mid-document and the parser errors.
_JUDGE_MAX_TOKENS = 3000

JUDGE_MODELS = {
    "judge_openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o",
        "env_keys": ["OPENAI_API_KEY", "GPT_API_KEY"],
        "header_fn": lambda key: {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        "body_fn": lambda model, system, prompt: {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "max_tokens": _JUDGE_MAX_TOKENS, "temperature": 0.3,
            "response_format": {"type": "json_object"},
        },
        "extract_fn": lambda data: data["choices"][0]["message"]["content"],
    },
    "judge_anthropic": {
        "url": "https://api.anthropic.com/v1/messages",
        "model": "claude-sonnet-4-6",
        "env_keys": ["ANTHROPIC_API_KEY", "CLAUDE_API_KEY"],
        "header_fn": lambda key: {
            "x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json",
        },
        "body_fn": lambda model, system, prompt: {
            "model": model, "max_tokens": _JUDGE_MAX_TOKENS,
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
        "env_keys": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
        "header_fn": lambda key: {"Content-Type": "application/json"},
        "body_fn": lambda model, system, prompt: {
            "contents": [{"role": "user", "parts": [{"text": system + "\n\n" + prompt}]}],
            # thinkingBudget=0 disables internal "thinking tokens" on Gemini 2.5
            # models — without it, a 1500-token cap can be entirely consumed by
            # invisible reasoning before any output is emitted (finishReason
            # ends up MAX_TOKENS with empty content).
            "generationConfig": {
                "maxOutputTokens": _JUDGE_MAX_TOKENS,
                "temperature": 0.3,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        },
        # Some models return content with no parts on edge cases; guard.
        "extract_fn": lambda data: (
            (data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", ""))
            or ""
        ),
    },
}


# Fallback chains: if primary fails, try these in order. Same-provider only
# (the call uses one config + api_key per judge). Fallbacks must NEVER climb
# the price curve — a flake on the cheap model shouldn't silently 25x the
# cost. The chain entry equal to the primary is a no-op (deduped against
# `tried` upstream), so listing it just documents intent.
JUDGE_FALLBACK_CHAINS = {
    "judge_openai": ["gpt-4o-mini"],                            # cheapest OpenAI tier; no further fallback
    "judge_anthropic": ["claude-haiku-4-5-20251001"],           # cheapest Anthropic tier; no further fallback
    "judge_google": ["gemini-2.5-flash", "gemini-2.5-flash-lite"],  # 2.0/1.5 flash are deprecated for new keys; flash-lite is the working fallback
}

MAX_RETRIES = 1


async def _call_judge_once(
    config: dict,
    api_key: str,
    model: str,
    system: str,
    user_prompt: str,
    timeout: int,
) -> dict:
    """Single attempt to call a judge model. Returns parsed JSON or error dict."""
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

            parsed = _try_parse_judge_json(raw_text)
            if parsed is not None:
                return parsed
            return {"error": "Judge returned no valid JSON", "raw": raw_text[:500]}

    except Exception as e:
        return {"error": str(e)[:200]}


def _try_parse_judge_json(text: str) -> dict | None:
    """Robust JSON extraction from a judge response.

    Anthropic in particular sometimes wraps JSON in markdown code fences or
    appends trailing prose. The greedy `{[\\s\\S]*}` match used to cut on the
    LAST `}` in the document — which fails when the model emits trailing
    explanatory text after a complete object. We try (in order):
      1. Direct json.loads on the whole string
      2. Strip ```json ... ``` fences and re-parse
      3. Find the first balanced top-level {...} via brace-counting
    """
    if not text:
        return None
    # 1. straight parse
    try:
        return json.loads(text)
    except Exception:
        pass
    # 2. strip code fences
    stripped = re.sub(r"^```(?:json)?\s*\n", "", text.strip(), flags=re.MULTILINE)
    stripped = re.sub(r"\n```\s*$", "", stripped.strip())
    if stripped != text:
        try:
            return json.loads(stripped)
        except Exception:
            pass
    # 3. find first balanced top-level object
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:i + 1]
                try:
                    return json.loads(candidate)
                except Exception:
                    return None
    return None


async def run_judge(
    judge_name: str,
    api_key: str,
    question: str,
    anonymized_options: dict[str, str],
    dimensions: list[dict],
    timeout: int = 300,
    model_override: str | None = None,
    focus: str = "balanced",
    length: str = "standard",
    perspective: str = "general",
    attachments: list[str] | None = None,
) -> dict:
    """Run a single judge evaluation with retry + fallback.

    Strategy:
    1. Try primary model
    2. If it fails, retry once
    3. If retry fails, try fallback (cheaper) model
    4. If all fail, return error dict
    """
    config = JUDGE_MODELS.get(judge_name)
    if not config:
        return {"error": f"Unknown judge: {judge_name}"}

    system = build_judge_system(dimensions, focus=focus, length=length, perspective=perspective)
    user_prompt = build_judge_prompt(question, anonymized_options, attachments=attachments)
    primary_model = model_override or config["model"]

    # Attempt 1: primary model
    result = await _call_judge_once(config, api_key, primary_model, system, user_prompt, timeout)
    if "error" not in result:
        return result

    # Attempt 2: retry primary model (transient failures)
    result = await _call_judge_once(config, api_key, primary_model, system, user_prompt, timeout)
    if "error" not in result:
        return result

    # Attempt 3+: walk the fallback chain (try every model we haven't tried)
    tried = {primary_model}
    for fallback_model in JUDGE_FALLBACK_CHAINS.get(judge_name, []):
        if fallback_model in tried:
            continue
        tried.add(fallback_model)
        result = await _call_judge_once(config, api_key, fallback_model, system, user_prompt, timeout)
        if "error" not in result:
            result["_used_fallback"] = fallback_model
            return result

    # All attempts failed
    result["judge"] = judge_name
    result["_degraded"] = True
    return result
