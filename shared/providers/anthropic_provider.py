import time
import httpx
from .base import BaseProvider, ModelResult


class AnthropicProvider(BaseProvider):
    name = "claude-sonnet-4-6"
    provider = "anthropic"
    API_URL = "https://api.anthropic.com/v1/messages"

    async def complete(
        self,
        prompt: str,
        system: str = "",
        web_search: bool = False,
        cache_system: bool = False,
    ) -> ModelResult:
        """Call Claude.

        cache_system=True wraps the system prompt in an Anthropic
        prompt-cache block (`cache_control: {"type": "ephemeral"}`). For
        repeat callers in a 5-minute window the input cost on the cached
        block drops ~90%. Use only when the system prompt is stable
        across multiple calls (strategist, decision_maker), not for
        per-call dynamic system content.
        """
        start = time.time()
        body = {
            "model": self.model_id,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            if cache_system and len(system) > 1000:
                # Anthropic requires the cached block to be sizeable
                # (~1024 tokens / ~4000 chars minimum) for the cache to
                # actually engage. Below that threshold we skip caching
                # entirely to avoid a no-op tax on tiny prompts.
                body["system"] = [
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            else:
                body["system"] = system

        # Native web search via Anthropic's server-executed tool. Claude decides
        # whether to search; Anthropic runs the search and feeds results back
        # to the model within the same API call. Single round-trip — simpler
        # than an external search service.
        if web_search:
            body["tools"] = [{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 3,
            }]

        try:
            async with httpx.AsyncClient(timeout=self.httpx_timeout) as client:
                resp = await client.post(
                    self.API_URL,
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                try:
                    # When web_search runs, content includes server_tool_use +
                    # web_search_tool_result blocks alongside text. Concatenate
                    # ONLY text blocks for the final answer.
                    text_parts = [
                        block.get("text", "")
                        for block in (data.get("content") or [])
                        if block.get("type") == "text"
                    ]
                    content = "".join(text_parts).strip()
                    if not content:
                        return self._make_result(
                            "error",
                            error=f"Claude response had no text blocks (stop_reason={data.get('stop_reason')})",
                            start_time=start,
                        )
                except (KeyError, IndexError, TypeError) as e:
                    return self._make_result("error", error=f"Unexpected response format: {e}", start_time=start)
                return self._make_result("success", response_content=content, start_time=start)
        except httpx.TimeoutException as e:
            elapsed = int((time.time() - start) * 1000)
            return self._make_result("timeout", error=f"Timed out after {elapsed}ms ({type(e).__name__})", start_time=start)
        except httpx.HTTPStatusError as e:
            return self._make_result("error", error=f"HTTP {e.response.status_code}: {e.response.text[:200]}", start_time=start)
        except Exception as e:
            return self._make_result("error", error=str(e)[:200], start_time=start)
