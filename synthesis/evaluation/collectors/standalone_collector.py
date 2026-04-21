"""
Collect outputs from standalone AI models via direct API calls.
Each model gets the raw prompt with no orchestration.
"""

import time
import httpx

from shared.providers.base import make_httpx_timeout


PROVIDER_CONFIGS = {
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o",
        "label": "GPT-4o (standalone)",
        "env_key": "openai_api_key",
        "header_fn": lambda key: {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        "body_fn": lambda model, prompt, system: {
            "model": model, "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ], "max_tokens": 4096, "temperature": 0.7,
        },
        "extract_fn": lambda data: data["choices"][0]["message"]["content"],
    },
    "anthropic": {
        "url": "https://api.anthropic.com/v1/messages",
        "model": "claude-sonnet-4-6",
        "label": "Claude Sonnet 4.6 (standalone)",
        "env_key": "anthropic_api_key",
        "header_fn": lambda key: {
            "x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json",
        },
        "body_fn": lambda model, prompt, system: {
            "model": model, "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        },
        "extract_fn": lambda data: data["content"][0]["text"],
    },
    "google": {
        "url_fn": lambda model, key: (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{model}:generateContent?key={key}"
        ),
        "model": "gemini-2.5-flash",
        "label": "Gemini 2.5 Flash (standalone)",
        "env_key": "google_api_key",
        "header_fn": lambda key: {"Content-Type": "application/json"},
        "body_fn": lambda model, prompt, system: {
            "contents": [{"role": "user", "parts": [{"text": system + "\n\n" + prompt}]}],
            "generationConfig": {"maxOutputTokens": 4096, "temperature": 0.7},
        },
        "extract_fn": lambda data: data["candidates"][0]["content"]["parts"][0]["text"],
    },
}

STANDALONE_SYSTEM = (
    "You are a senior strategist and analyst. "
    "Provide thorough, specific, and actionable analysis. "
    "Be detailed and avoid generic advice. "
    "Structure your response clearly with headers and bullet points where appropriate."
)


async def collect_standalone_output(
    prompt: str,
    provider_name: str,
    api_key: str,
    timeout: int = 600,
) -> dict:
    """Call a standalone model directly and collect the output.

    Returns:
        {
            "system": "standalone_<provider>",
            "model": str,
            "label": str,
            "final_output": str,
            "runtime_ms": int,
            "error": str | None,
        }
    """
    config = PROVIDER_CONFIGS.get(provider_name)
    if not config:
        return {"system": f"standalone_{provider_name}", "error": f"Unknown provider: {provider_name}"}

    model = config["model"]
    label = config["label"]
    headers = config["header_fn"](api_key)
    body = config["body_fn"](model, prompt, STANDALONE_SYSTEM)

    # Determine URL
    if "url_fn" in config:
        url = config["url_fn"](model, api_key)
    else:
        url = config["url"]

    start = time.time()
    ht = make_httpx_timeout(timeout)

    try:
        async with httpx.AsyncClient(timeout=ht) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            content = config["extract_fn"](data)
            runtime_ms = int((time.time() - start) * 1000)

            return {
                "system": f"standalone_{provider_name}",
                "model": model,
                "label": label,
                "final_output": content,
                "runtime_ms": runtime_ms,
                "error": None,
            }
    except httpx.TimeoutException:
        return {
            "system": f"standalone_{provider_name}",
            "model": model, "label": label,
            "final_output": "",
            "runtime_ms": int((time.time() - start) * 1000),
            "error": "Timeout",
        }
    except httpx.HTTPStatusError as e:
        return {
            "system": f"standalone_{provider_name}",
            "model": model, "label": label,
            "final_output": "",
            "runtime_ms": int((time.time() - start) * 1000),
            "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
        }
    except Exception as e:
        return {
            "system": f"standalone_{provider_name}",
            "model": model, "label": label,
            "final_output": "",
            "runtime_ms": int((time.time() - start) * 1000),
            "error": str(e)[:200],
        }
