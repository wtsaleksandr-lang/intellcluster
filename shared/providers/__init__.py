"""
Provider registry for Decision Intelligence Tool.
Ported from ai-orchestrator — adapted for judge-only usage.
"""

import os

from .base import BaseProvider, CircuitBreaker, ModelResult
from .openai_provider import OpenAIProvider
from .anthropic_provider import AnthropicProvider
from .google_provider import GoogleProvider
from .deepseek_provider import DeepSeekProvider
from .xai_provider import XAIProvider

_PROVIDER_CLASSES: dict[str, type[BaseProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
    "deepseek": DeepSeekProvider,
    "xai": XAIProvider,
}

circuit_breaker = CircuitBreaker(threshold=3)

# API key env var names (supports aliases from ai-orchestrator)
_API_KEY_ALIASES = {
    "openai": ["OPENAI_API_KEY", "GPT_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY", "CLAUDE_API_KEY"],
    "google": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY"],
    "xai": ["XAI_API_KEY", "GROK_API_KEY"],
}

# Model → provider name
_MODEL_PROVIDER: dict[str, str] = {
    "gpt-4o": "openai",
    "gpt-4o-mini": "openai",
    "claude-sonnet-4-6": "anthropic",
    "claude-haiku-4-5-20251001": "anthropic",
    "gemini-2.5-flash": "google",
    "deepseek-chat": "deepseek",
    "grok-3": "xai",
}


def get_api_key(provider_name: str) -> str | None:
    aliases = _API_KEY_ALIASES.get(provider_name, [])
    for env_var in aliases:
        val = os.environ.get(env_var)
        if val:
            return val
    return None


def get_provider(model_name: str, timeout: int = 300) -> BaseProvider | None:
    """Get an initialized provider for a model name. Returns None if unavailable."""
    provider_name = _MODEL_PROVIDER.get(model_name)
    if not provider_name:
        return None

    if circuit_breaker.is_open(model_name):
        return None

    api_key = get_api_key(provider_name)
    if not api_key:
        return None

    cls = _PROVIDER_CLASSES[provider_name]
    return cls(api_key=api_key, model_id=model_name, timeout=timeout)


def get_available_judges(timeout: int = 300) -> list[tuple[str, BaseProvider]]:
    """Get all available judge providers (one per provider that has an API key)."""
    judge_models = [
        ("judge_openai", "gpt-4o"),
        ("judge_anthropic", "claude-sonnet-4-6"),
        ("judge_google", "gemini-2.5-flash"),
    ]
    available = []
    for judge_name, model in judge_models:
        provider = get_provider(model, timeout=timeout)
        if provider:
            available.append((judge_name, provider))
    return available
