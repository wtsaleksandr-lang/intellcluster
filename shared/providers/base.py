"""
Base provider interface and utilities.
Ported from ai-orchestrator.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import time

import httpx


@dataclass
class ModelResult:
    """Normalized response from any LLM provider."""
    model_name: str
    status: str  # "success" | "timeout" | "error"
    response_content: str | None = None
    latency_ms: int = 0
    error: str | None = None


class CircuitBreaker:
    """Simple circuit breaker: disables a model after N consecutive failures."""

    def __init__(self, threshold: int = 3):
        self.threshold = threshold
        self._failures: dict[str, int] = {}
        self._open: set[str] = set()

    def is_open(self, model: str) -> bool:
        return model in self._open

    def record_success(self, model: str):
        self._failures[model] = 0
        self._open.discard(model)

    def record_failure(self, model: str):
        self._failures[model] = self._failures.get(model, 0) + 1
        if self._failures[model] >= self.threshold:
            self._open.add(model)

    def reset(self):
        self._failures.clear()
        self._open.clear()


def make_httpx_timeout(timeout_seconds: int) -> httpx.Timeout:
    """Build an explicit httpx.Timeout with generous connect/pool limits."""
    return httpx.Timeout(
        connect=30.0,
        read=float(timeout_seconds),
        write=60.0,
        pool=60.0,
    )


class BaseProvider(ABC):
    """Abstract base for all LLM provider adapters."""

    name: str
    provider: str

    def __init__(self, api_key: str, model_id: str | None = None, timeout: int = 300):
        self.api_key = api_key
        self.model_id = model_id or self.name
        self.timeout = timeout
        self.httpx_timeout = make_httpx_timeout(timeout)

    @abstractmethod
    async def complete(self, prompt: str, system: str = "", web_search: bool = False) -> ModelResult:
        ...

    def _make_result(
        self,
        status: str,
        response_content: str | None = None,
        error: str | None = None,
        start_time: float = 0,
    ) -> ModelResult:
        latency = int((time.time() - start_time) * 1000) if start_time else 0
        return ModelResult(
            model_name=self.name,
            status=status,
            response_content=response_content,
            latency_ms=latency,
            error=error,
        )
