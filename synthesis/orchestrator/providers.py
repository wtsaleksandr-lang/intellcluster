"""
Synthesis providers wrapper — adds settings-aware routing on top of shared.providers.
Replaces the old orchestrator/providers/__init__.py.
"""

from synthesis.config import settings
from shared.providers.base import BaseProvider, CircuitBreaker, ModelResult
from shared.providers.openai_provider import OpenAIProvider
from shared.providers.anthropic_provider import AnthropicProvider
from shared.providers.google_provider import GoogleProvider
from shared.providers.deepseek_provider import DeepSeekProvider
from shared.providers.xai_provider import XAIProvider

# Provider class registry: provider_name -> class
_PROVIDER_CLASSES: dict[str, type[BaseProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
    "deepseek": DeepSeekProvider,
    "xai": XAIProvider,
}

# Session-level circuit breaker (shared across runs)
circuit_breaker = CircuitBreaker(threshold=settings.circuit_breaker_threshold)


def _get_model_registry() -> dict[str, tuple[str, type[BaseProvider]]]:
    """Build model_name -> (provider_name, ProviderClass) from config."""
    registry = {
        settings.openai_model_id: ("openai", OpenAIProvider),
        settings.anthropic_model_id: ("anthropic", AnthropicProvider),
        settings.google_model_id: ("google", GoogleProvider),
        settings.deepseek_model_id: ("deepseek", DeepSeekProvider),
        settings.xai_model_id: ("xai", XAIProvider),
        "gpt-4o-mini": ("openai", OpenAIProvider),
        "claude-haiku-4-5-20251001": ("anthropic", AnthropicProvider),
    }
    for model_id in [
        settings.expert_strategist_model,
        settings.expert_decision_maker_model,
        settings.expert_prompt_engineer_model,
        settings.cheap_strategist_model,
        settings.cheap_decision_maker_model,
    ]:
        if model_id not in registry:
            provider_map = settings._model_provider_map()
            if model_id in provider_map:
                pname = provider_map[model_id]
                registry[model_id] = (pname, _PROVIDER_CLASSES[pname])
    return registry


def get_provider(model_name: str, role: str | None = None) -> BaseProvider | None:
    """Get an initialized provider instance for a model name."""
    timeout = settings.get_timeout_for_role(role) if role else settings.safety_timeout_seconds

    if settings.test_mode:
        from shared.providers.mock_provider import MockProvider
        return MockProvider(model_id=model_name, timeout=timeout)

    registry = _get_model_registry()
    entry = registry.get(model_name)
    if not entry:
        return None

    provider_name, cls = entry
    api_key = settings.get_api_key(provider_name)
    if not api_key:
        return None

    return cls(api_key=api_key, model_id=model_name, timeout=timeout)


def get_providers(model_names: list[str], role: str | None = None) -> list[BaseProvider]:
    """Get provider instances for multiple models."""
    providers = []
    for name in model_names:
        if circuit_breaker.is_open(name):
            continue
        provider = get_provider(name, role=role)
        if provider:
            providers.append(provider)
    return providers


def get_provider_for_role(role: str, tier: str = "standard") -> BaseProvider:
    """Get the provider for a specific agent role at a specific tier."""
    model_name, _ = settings.get_role_model_for_tier(role, tier)

    if model_name:
        provider = get_provider(model_name, role=role)
        if provider:
            return provider

    for model in settings.enabled_models:
        provider = get_provider(model, role=role)
        if provider:
            return provider

    raise RuntimeError(f"No LLM provider available for role '{role}'. Check API keys and config.")


async def call_with_role_fallback(role: str, prompt: str, system: str = "", tier: str = "standard", cache_system: bool = False) -> tuple[ModelResult, str]:
    """Call a provider for a role, falling back on failure.

    cache_system=True hints that the `system` prompt is stable enough to
    cache. Forwarded only to providers that support it (currently
    Anthropic). Other providers ignore the hint.
    """
    configured_model, _ = settings.get_role_model_for_tier(role, tier)

    candidates = []
    if configured_model:
        p = get_provider(configured_model, role=role)
        if p:
            candidates.append(p)

    for model in settings.enabled_models:
        if model != configured_model:
            p = get_provider(model, role=role)
            if p:
                candidates.append(p)

    if not candidates:
        return ModelResult(model_name="none", status="error", response_content=None,
                           error=f"No providers available for role '{role}'"), "none"

    last_error = None
    tried = []
    for provider in candidates:
        # Only Anthropic implements cache_system today; pass it conditionally
        # so other providers don't see an unexpected kwarg.
        extra: dict = {}
        if cache_system and getattr(provider, "provider", "") == "anthropic":
            extra["cache_system"] = True
        result = await provider.complete(prompt=prompt, system=system, **extra)
        tried.append(provider.name)
        if result.status == "success" and result.response_content:
            return result, provider.name
        last_error = result

    error_msg = f"All {len(tried)} providers failed for role '{role}': {tried}"
    if last_error and last_error.error:
        error_msg += f". Last error: {last_error.error}"
    return ModelResult(model_name=tried[-1] if tried else "none", status="error",
                       response_content=None, error=error_msg), tried[-1] if tried else "none"
