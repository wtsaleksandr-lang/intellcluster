from __future__ import annotations

from time import monotonic

from fastapi import Request
from fastapi.responses import Response

_CACHE_TTLS = {
    "/sitemap.xml": 900,
    "/sitemaps/intelligence.xml": 21_600,
    "/sitemaps/suppliers.xml": 21_600,
}
_CACHE: dict[str, tuple[float, bytes, dict[str, str], str]] = {}


def install_sitemap_cache(app) -> None:
    """Cache aggregate-heavy sitemap responses in each application worker.

    Company sitemap pages remain uncached because their indexed rows can change
    quickly during ingestion. The analytical and supplier sitemaps are expensive
    aggregate queries and are safe to refresh on a slower cadence.
    """
    if getattr(app.state, "intellcluster_sitemap_cache_installed", False):
        return
    app.state.intellcluster_sitemap_cache_installed = True

    @app.middleware("http")
    async def sitemap_response_cache(request: Request, call_next):
        path = request.url.path
        ttl = _CACHE_TTLS.get(path)
        if ttl is None or request.method != "GET" or request.query_params:
            return await call_next(request)

        cached = _CACHE.get(path)
        now = monotonic()
        if cached and cached[0] > now:
            _, body, headers, media_type = cached
            return Response(body, status_code=200, headers=headers, media_type=media_type)

        response = await call_next(request)
        if response.status_code != 200:
            return response
        content_type = response.headers.get("content-type", "")
        if "xml" not in content_type:
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        headers = dict(response.headers)
        headers.pop("content-length", None)
        media_type = content_type.split(";", 1)[0] or "application/xml"
        _CACHE[path] = (now + ttl, body, headers, media_type)
        return Response(body, status_code=200, headers=headers, media_type=media_type)
