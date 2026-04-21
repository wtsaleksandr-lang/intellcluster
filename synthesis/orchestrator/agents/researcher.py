"""
Research Agent (Single-Model Caller)
- Calls a single LLM with retry on transient failures
- Returns normalized ModelResult
- Pipeline handles parallel orchestration and streaming
"""

import asyncio

from synthesis.config import settings
from synthesis.orchestrator.providers import circuit_breaker
from shared.providers.base import BaseProvider, ModelResult


async def call_model(
    provider: BaseProvider,
    prompt: str,
    system: str,
    max_retries: int | None = None,
    web_search: bool = False,
) -> ModelResult:
    """Call a single model with retry on transient failures.

    If web_search=True, enables provider-specific web search API features.
    """
    if max_retries is None:
        max_retries = settings.max_retries

    for attempt in range(1 + max_retries):
        try:
            result = await provider.complete(prompt, system, web_search=web_search)

            # Treat success with empty content as a failure
            if result.status == "success" and not result.response_content:
                circuit_breaker.record_failure(provider.name)
                if attempt < max_retries:
                    continue
                result.status = "error"
                result.error = "Success but empty response content"
                return result

            if result.status == "success":
                circuit_breaker.record_success(provider.name)
            else:
                # Don't trip the circuit breaker on transient server-side errors.
                # 503 = service overload (temporary), 429 = rate limit (temporary).
                # Only hard client-side errors (auth/bad model) should count.
                is_transient = result.error and (
                    "HTTP 503" in result.error or
                    "HTTP 429" in result.error or
                    result.status == "timeout"
                )
                if not is_transient:
                    circuit_breaker.record_failure(provider.name)

            # Retry on transient failures (timeout, 503 overload, network errors)
            if result.status in ("timeout", "error") and attempt < max_retries:
                if result.error and "HTTP 4" in result.error and "HTTP 429" not in result.error:
                    return result  # Hard client error — don't retry
                # Backoff on 503 (service overload)
                if result.error and "HTTP 503" in result.error:
                    await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s
                continue

            return result

        except asyncio.CancelledError:
            return ModelResult(
                model_name=provider.name,
                status="cancelled",
                response_content=None,
                error="Cancelled by user",
            )
        except Exception as e:
            circuit_breaker.record_failure(provider.name)
            if attempt < max_retries:
                continue
            return ModelResult(
                model_name=provider.name,
                status="error",
                response_content=None,
                error=str(e)[:200],
            )

    return ModelResult(
        model_name=provider.name,
        status="error",
        response_content=None,
        error="Max retries exceeded",
    )


def truncate_output(result: ModelResult) -> ModelResult:
    """Truncate response_content to max_model_output_chars."""
    if result.response_content and len(result.response_content) > settings.max_model_output_chars:
        result.response_content = (
            result.response_content[:settings.max_model_output_chars]
            + f"\n\n[Truncated at {settings.max_model_output_chars} chars]"
        )
    return result
