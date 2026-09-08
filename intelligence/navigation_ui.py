from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response

_DESKTOP_NEEDLE = '<a href="/pricing" class="nav-tool">Pricing</a>'
_DESKTOP_REPLACEMENT = (
    '<a href="/data" class="nav-tool" data-intelligence-nav="desktop">Data</a>\n      '
    + _DESKTOP_NEEDLE
)
_MOBILE_NEEDLE = '    <a href="/pricing">Pricing</a>'
_MOBILE_REPLACEMENT = (
    '    <a href="/data" data-intelligence-nav="mobile">Business Intelligence</a>\n'
    + _MOBILE_NEEDLE
)
_FOOTER_NEEDLE = '          <li><a href="/advisory">Advisory Council</a></li>'
_FOOTER_REPLACEMENT = (
    '          <li><a href="/data" data-intelligence-nav="footer">Business Intelligence</a></li>\n'
    + _FOOTER_NEEDLE
)


def install_intelligence_navigation(app) -> None:
    """Add the data product to the shared site navigation without duplicating templates.

    The core application owns one large shared base template used by many existing
    product pages. The production intelligence entrypoint wraps that core app, so a
    narrow response enhancer keeps the business-directory launch discoverable from
    desktop, mobile and footer navigation while avoiding a risky full-template fork.
    """
    if getattr(app.state, "intellcluster_intelligence_navigation_installed", False):
        return
    app.state.intellcluster_intelligence_navigation_installed = True

    @app.middleware("http")
    async def intelligence_navigation(request: Request, call_next):
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if request.method != "GET" or "text/html" not in content_type:
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        text = body.decode("utf-8", errors="replace")

        if 'data-intelligence-nav="desktop"' not in text:
            text = text.replace(_DESKTOP_NEEDLE, _DESKTOP_REPLACEMENT, 1)
        if 'data-intelligence-nav="mobile"' not in text:
            text = text.replace(_MOBILE_NEEDLE, _MOBILE_REPLACEMENT, 1)
        if 'data-intelligence-nav="footer"' not in text:
            text = text.replace(_FOOTER_NEEDLE, _FOOTER_REPLACEMENT, 1)

        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            text,
            status_code=response.status_code,
            headers=headers,
            media_type="text/html",
        )
