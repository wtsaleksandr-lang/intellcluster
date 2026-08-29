from __future__ import annotations

import re

from fastapi import Request
from fastapi.responses import Response


_DEMO_NOTICE = "Preview fallback — no live rows matched this query."
_EMPTY_NOTICE = (
    "No matching company profiles were found. Try a broader company name, remove a filter, "
    "or switch between Canada and USA."
)
_EMPTY_HEADER = "x-intellcluster-empty-search"


def install_search_empty_state(app) -> None:
    """Render a useful zero-result state while guaranteeing no demo result card appears."""
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
        explicit_empty = response.headers.get(_EMPTY_HEADER) == "1"
        legacy_demo = _DEMO_NOTICE in text

        if explicit_empty:
            notice = f'<div class="notice">{_EMPTY_NOTICE}</div>'
            text = text.replace(
                '<div class="search-toolbar">',
                notice + '<div class="search-toolbar">',
                1,
            )
            text = re.sub(
                r'(<div\s+class="result-meta"[^>]*>\s*<span>).*?(</span>)',
                r"\1No matching business profiles found\2",
                text,
                count=1,
                flags=re.DOTALL | re.IGNORECASE,
            )
        elif legacy_demo:
            # Backward-compatible protection for any older deployment that still
            # renders the historical demo fallback. The new canonical search route
            # does not emit it, but keeping this guard prevents fake results during
            # rolling deployments.
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
        headers.pop("x-intellcluster-empty-search", None)
        return Response(
            content=text,
            status_code=response.status_code,
            headers=headers,
            media_type="text/html",
        )
