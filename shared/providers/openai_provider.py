import time
import httpx
from .base import BaseProvider, ModelResult


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

        body = {
            "model": self.model_id,
            "messages": messages,
            "max_tokens": 4096,
            "temperature": 0.3,
        }

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
                return self._make_result("success", response_content=content, start_time=start)
        except httpx.TimeoutException as e:
            elapsed = int((time.time() - start) * 1000)
            return self._make_result("timeout", error=f"Timed out after {elapsed}ms ({type(e).__name__})", start_time=start)
        except httpx.HTTPStatusError as e:
            return self._make_result("error", error=f"HTTP {e.response.status_code}: {e.response.text[:200]}", start_time=start)
        except Exception as e:
            return self._make_result("error", error=str(e)[:200], start_time=start)
