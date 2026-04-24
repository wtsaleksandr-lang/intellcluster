import time
import httpx
from .base import BaseProvider, ModelResult


# Map base → search-preview variants. When web_search=True we swap the model
# to its search-capable counterpart. Search-preview variants execute web
# searches automatically inside the single chat completion — no tools param
# required, same endpoint. Pricing + rate limits differ slightly but the
# request shape stays identical.
SEARCH_MODEL_MAP = {
    "gpt-4o":      "gpt-4o-search-preview",
    "gpt-4o-mini": "gpt-4o-mini-search-preview",
}


class OpenAIProvider(BaseProvider):
    name = "gpt-4o"
    provider = "openai"
    API_URL = "https://api.openai.com/v1/chat/completions"

    async def complete(self, prompt: str, system: str = "", web_search: bool = False) -> ModelResult:
        start = time.time()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # Resolve the effective model. When the caller asks for web_search and
        # we have a search-preview variant, swap in. Otherwise pass through.
        effective_model = self.model_id
        if web_search and self.model_id in SEARCH_MODEL_MAP:
            effective_model = SEARCH_MODEL_MAP[self.model_id]

        body = {
            "model": effective_model,
            "messages": messages,
            "max_tokens": 4096,
        }
        # Search-preview models don't accept temperature (fixed internally).
        if not effective_model.endswith("-search-preview"):
            body["temperature"] = 0.3

        try:
            async with httpx.AsyncClient(timeout=self.httpx_timeout) as client:
                resp = await client.post(
                    self.API_URL,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                try:
                    content = data["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as e:
                    return self._make_result("error", error=f"Unexpected response format: {e}", start_time=start)
                result = self._make_result("success", response_content=content, start_time=start)
                # Record which model actually answered so downstream cost
                # tracking + admin dashboards see the search-preview swap.
                result.model_name = effective_model
                return result
        except httpx.TimeoutException as e:
            elapsed = int((time.time() - start) * 1000)
            return self._make_result("timeout", error=f"Timed out after {elapsed}ms ({type(e).__name__})", start_time=start)
        except httpx.HTTPStatusError as e:
            return self._make_result("error", error=f"HTTP {e.response.status_code}: {e.response.text[:200]}", start_time=start)
        except Exception as e:
            return self._make_result("error", error=str(e)[:200], start_time=start)
