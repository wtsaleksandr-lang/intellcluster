import time
import httpx
from .base import BaseProvider, ModelResult

FALLBACK_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash"]


class GoogleProvider(BaseProvider):
    name = "gemini-2.5-flash"
    provider = "google"

    def _api_url(self, model_id: str) -> str:
        return (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{model_id}:generateContent?key={self.api_key}"
        )

    async def _call(self, model_id: str, body: dict, start: float) -> ModelResult:
        try:
            async with httpx.AsyncClient(timeout=self.httpx_timeout) as client:
                resp = await client.post(
                    self._api_url(model_id),
                    headers={"Content-Type": "application/json"},
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                try:
                    content = data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError, TypeError) as e:
                    return self._make_result("error", error=f"Unexpected response format: {e}", start_time=start)
                result = self._make_result("success", response_content=content, start_time=start)
                result.model_name = model_id
                return result
        except httpx.TimeoutException as e:
            elapsed = int((time.time() - start) * 1000)
            return self._make_result("timeout", error=f"Timed out after {elapsed}ms ({type(e).__name__})", start_time=start)
        except httpx.HTTPStatusError as e:
            return self._make_result("error", error=f"HTTP {e.response.status_code}: {e.response.text[:200]}", start_time=start)
        except Exception as e:
            return self._make_result("error", error=str(e)[:200], start_time=start)

    async def complete(self, prompt: str, system: str = "", web_search: bool = False) -> ModelResult:
        start = time.time()
        text = system + "\n\n" + prompt if system else prompt
        body = {
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {"maxOutputTokens": 4096, "temperature": 0.3},
        }
        if web_search:
            body["tools"] = [{"google_search": {}}]

        result = await self._call(self.model_id, body, start)
        if result.status == "success":
            return result

        if result.error and "503" in result.error:
            for fb_model in FALLBACK_MODELS:
                if fb_model == self.model_id:
                    continue
                fb_result = await self._call(fb_model, body, start)
                if fb_result.status == "success":
                    return fb_result

        return result
