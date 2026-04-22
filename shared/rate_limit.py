"""
Simple in-memory rate limiter — per-IP sliding window.
For production with multiple workers, swap to Redis.
"""

import os
import time
from collections import defaultdict, deque
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse


# IP -> deque of recent request timestamps
_buckets: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))


def _client_ip(request: Request) -> str:
    """Get client IP, respecting proxy headers."""
    # Railway/Render/Fly set X-Forwarded-For
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client:
        return request.client.host
    return "unknown"


def _enabled() -> bool:
    return os.environ.get("RATE_LIMIT_ENABLED", "true").lower() == "true"


def _limit() -> int:
    try:
        return int(os.environ.get("RATE_LIMIT_PER_MINUTE", "30"))
    except ValueError:
        return 30


async def rate_limit_middleware(request: Request, call_next):
    """Rate limit middleware. Applies per-IP sliding window of 60s."""
    if not _enabled():
        return await call_next(request)

    path = request.url.path
    # Only rate-limit API endpoints (HTML pages are fine)
    if not path.startswith("/api/") and not (path.startswith("/phronesis/api/") or path.startswith("/synthesis/api/")):
        return await call_next(request)
    # Allow health unconditionally
    if path == "/api/health":
        return await call_next(request)

    ip = _client_ip(request)
    now = time.time()
    bucket = _buckets[ip]
    window = 60.0
    limit = _limit()

    # Drop old entries
    while bucket and bucket[0] < now - window:
        bucket.popleft()

    if len(bucket) >= limit:
        retry_after = int(bucket[0] + window - now) + 1
        reset_at = int(bucket[0] + window)
        return JSONResponse(
            status_code=429,
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset_at),
            },
            content={"error": "Rate limit exceeded. Try again in a few seconds.", "retry_after_seconds": retry_after},
        )

    bucket.append(now)
    remaining = max(0, limit - len(bucket))
    reset_at = int(bucket[0] + window) if bucket else int(now + window)

    response = await call_next(request)
    # Expose rate-limit state so clients can show usage without a round trip.
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(reset_at)
    return response
