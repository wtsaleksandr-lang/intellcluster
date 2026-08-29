from __future__ import annotations

import re

from fastapi import Request
from fastapi.responses import Response


_DEMO_NOTICE = "Preview fallback — no live rows matched this query."
_EMPTY_NOTICE = (
    "No matching company profiles were found. Try a broader company name, remove a filter, "
    "or switch between Canada and USA."
)


def install_search_empty_state(app) -> None:
    """Prevent demo companies from appearing as if they matched a real search."""
    if getattr(app.state, "intellcluster_search_empty_state_installed", False):
        return
    app.state.intellcluster_search_empty_state_installed = True

    @app.middleware("http")
    async def search_empty_state(request: Request, call_next):
        response = await call_next(request)
        if (
            request.method != "GET"
            or request.url.path != "/data/search"
            or response.status_code != 200
            or "text/html" not in response.headers.get("content-type", "")
        ):
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        text = body.decode("utf-8", errors="replace")
        if _DEMO_NOTICE not in text:
            headers = dict(response.headers)
            headers.pop("content-length", None)
            return Response(
                content=text,
                status_code=response.status_code,
                headers=headers,
                media_type="text/html",
            )

        text = text.replace(_DEMO_NOTICE, _EMPTY_NOTICE, 1)
        text = re.sub(
            r'<article\s+class="card[^>]*>.*?</article>',
            "",
            text,
            count=1,
            flags=re.DOTALL | re.IGNORECASE,
        )
        text = re.sub(
            r'(<div\s+class="result-meta"[^>]*>\s*<span>).*?(</span>)',
            r"\1No matching business profiles found\2",
            text,
            count=1,
            flags=re.DOTALL | re.IGNORECASE,
        )
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=text,
            status_code=response.status_code,
            headers=headers,
            media_type="text/html",
        )
