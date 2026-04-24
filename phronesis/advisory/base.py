"""
Base Agent class — every Phronesis OS agent inherits from this.

Responsibilities handled here, so individual agents only have to write a prompt
and a parse function:

  * Model selection (via shared.providers) with graceful fallback
  * JSON response enforcement + parsing
  * Cost tracking on each call
  * Latency measurement
  * Circuit-breaker compliance
  * Consistent AgentOutput with error-on-failure instead of raising
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from typing import Any

from shared.providers import get_provider, get_api_key

from .types import AgentOutput


# Default model chosen per agent "temperament" — cheap+fast for structuring,
# higher-tier for nuance and final writing.
MODEL_TIERS = {
    "fast":    ["gpt-4o-mini", "claude-haiku-4-5-20251001", "gemini-2.5-flash"],
    "balanced": ["claude-haiku-4-5-20251001", "gpt-4o-mini"],
    "nuanced": ["claude-sonnet-4-6", "gpt-4o", "claude-haiku-4-5-20251001"],
    "writer":  ["claude-sonnet-4-6", "gpt-4o"],
}


# Retry policy — 2 attempts total (1 retry after initial failure).
# We only retry on transient failures (timeouts, 5xx, network) — not on JSON
# parse errors or auth failures, which won't recover from a retry.
RETRY_ATTEMPTS = 2
RETRY_BASE_DELAY = 0.5      # seconds
RETRY_MAX_DELAY = 4.0
TRANSIENT_MARKERS = (
    "timeout", "timed out", "read timeout", "connection",
    "temporarily unavailable", "rate limit", "429", "500", "502", "503", "504",
    "service unavailable", "gateway", "overloaded",
)


def _is_transient(error_text: str) -> bool:
    e = (error_text or "").lower()
    return any(m in e for m in TRANSIENT_MARKERS)


def _retry_delay(attempt: int) -> float:
    """Exponential backoff with full jitter, capped at RETRY_MAX_DELAY."""
    raw = RETRY_BASE_DELAY * (2 ** attempt)
    return min(RETRY_MAX_DELAY, random.uniform(0, raw))


def _extract_json(raw: str) -> dict[str, Any] | None:
    """Pull the first JSON object out of a model response, tolerant of code fences."""
    if not raw:
        return None
    # strip common fences
    raw = raw.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    # direct parse first
    try:
        return json.loads(raw)
    except Exception:
        pass
    # greedy find
    m = re.search(r'\{[\s\S]*\}', raw)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except Exception:
        return None


class Agent:
    """
    Subclasses define:
      name:          short identifier, used in AgentOutput.agent
      tier:          one of MODEL_TIERS keys
      system_prompt: the agent's role instruction
      user_template: f-string with `{...}` placeholders filled by build_user()
      json_mode:     if True, parse response as JSON and populate AgentOutput.raw
      temperature:   override default (0.3)

    Override:
      build_user(session, **kwargs) → str
      parse(raw, session, **kwargs) → AgentOutput
    """

    name: str = "agent"
    tier: str = "fast"
    system_prompt: str = ""
    user_template: str = ""
    json_mode: bool = True
    temperature: float = 0.3
    timeout: int = 90

    def __init__(self):
        self.model_name: str | None = None

    # ─── Model selection ───

    def _pick_model(self) -> str | None:
        """Walk the tier's preference list; return the first model with a key."""
        for model in MODEL_TIERS.get(self.tier, MODEL_TIERS["fast"]):
            # lowercase family check
            if "gpt" in model and not get_api_key("openai"):
                continue
            if "claude" in model and not get_api_key("anthropic"):
                continue
            if "gemini" in model and not get_api_key("google"):
                continue
            return model
        return None

    # ─── Core run ───

    async def run(self, **kwargs) -> AgentOutput:
        """Produce an AgentOutput. Never raises — errors come back as status='error'."""
        start = time.time()

        user_msg = self.build_user(**kwargs)
        if not user_msg:
            return AgentOutput(
                agent=self.name,
                status="skipped",
                summary="(skipped — no input)",
            )

        model = self._pick_model()
        if not model:
            return AgentOutput(
                agent=self.name,
                status="error",
                error="No model provider available for this agent's tier.",
            )
        self.model_name = model

        provider = get_provider(model, timeout=self.timeout)
        if not provider:
            return AgentOutput(
                agent=self.name,
                status="error",
                error=f"Provider for {model} unavailable (circuit open or key missing).",
            )

        # ─── Retry loop: up to RETRY_ATTEMPTS total on transient failures ───
        last_error: str | None = None
        result = None
        retries_used = 0
        for attempt in range(RETRY_ATTEMPTS):
            try:
                result = await provider.complete(
                    prompt=user_msg,
                    system=self.system_prompt,
                )
                call_error = None if result.status == "success" else (result.error or result.status)
            except Exception as e:
                result = None
                call_error = f"exception: {str(e)[:200]}"

            if result is not None and result.status == "success":
                break

            last_error = call_error
            # Don't retry on the final attempt, or on non-transient failures
            if attempt == RETRY_ATTEMPTS - 1 or not _is_transient(call_error or ""):
                break

            retries_used += 1
            await asyncio.sleep(_retry_delay(attempt))

        latency_ms = int((time.time() - start) * 1000)

        if result is None or result.status != "success":
            return AgentOutput(
                agent=self.name,
                status="error",
                error=(last_error or "unknown")[:240] + (
                    f" (after {retries_used} retry)" if retries_used else ""
                ),
                model=model,
                latency_ms=latency_ms,
                raw={"retries_used": retries_used},
            )

        raw_text = result.response_content or ""

        if self.json_mode:
            parsed = _extract_json(raw_text)
            if parsed is None:
                return AgentOutput(
                    agent=self.name,
                    status="error",
                    error=f"Could not parse JSON from {model}: {raw_text[:160]}",
                    model=model,
                    latency_ms=latency_ms,
                )
        else:
            parsed = {"text": raw_text}

        output = self.parse(parsed, **kwargs)
        output.model = model
        output.latency_ms = latency_ms

        # Rough cost estimate — providers don't return usage uniformly; use char count.
        output.cost_usd = self._estimate_cost(model, len(user_msg), len(raw_text))

        return output

    # ─── To override in subclasses ───

    def build_user(self, **kwargs) -> str:
        """Return the user-role prompt for this agent. Empty string → skip."""
        return self.user_template.format(**kwargs)

    def parse(self, data: dict[str, Any], **kwargs) -> AgentOutput:
        """Turn the parsed JSON/text into an AgentOutput. Default just stores raw."""
        return AgentOutput(
            agent=self.name,
            status="ok",
            raw=data,
        )

    # ─── Utilities ───

    @staticmethod
    def _estimate_cost(model: str, input_chars: int, output_chars: int) -> float:
        """Rough per-1k-char cost proxy; real tallies happen in billing reconciliation."""
        tier_costs = {
            "gpt-4o-mini":                  (0.00015 / 1000, 0.0006 / 1000),
            "gpt-4o":                       (0.0025 / 1000,  0.01 / 1000),
            "claude-haiku-4-5-20251001":    (0.001 / 1000,   0.005 / 1000),
            "claude-sonnet-4-6":            (0.003 / 1000,   0.015 / 1000),
            "gemini-2.5-flash":             (0.00015 / 1000, 0.0006 / 1000),
        }
        in_rate, out_rate = tier_costs.get(model, (0.001 / 1000, 0.005 / 1000))
        # ~4 chars per token
        return round(in_rate * (input_chars / 4) + out_rate * (output_chars / 4), 6)
