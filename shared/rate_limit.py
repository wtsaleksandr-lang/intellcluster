"""
Sliding-window rate limiter with per-plan tiers.

Two big changes from the IP-only baseline:

  1. Identity resolution — we prefer session cookie → user email as the
     bucket key when a user is signed in, falling back to IP when they
     aren't. This means paid users aren't penalised by being behind the
     same NAT as free users.
  2. Per-plan caps — the limit is selected from PLAN_LIMITS by the
     user's plan (free / starter / pro / team). Anonymous traffic uses
     the free cap. Override per-env via RATE_LIMIT_PER_MINUTE (applies to
     anon + free tier only — paid tiers stay on the hardcoded table).

For a multi-worker deployment, swap the in-process dict for Redis; the
function signatures stay the same.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse


# key (ip|user:email) -> deque of recent timestamps
_buckets: dict[str, deque] = defaultdict(lambda: deque(maxlen=400))

# Counter to amortize the bucket-eviction sweep over many requests so we
# don't grow _buckets unbounded under attack-from-many-IPs scenarios.
_request_counter = 0
_GC_EVERY = 1000


def _maybe_gc_buckets(now: float) -> None:
    global _request_counter
    _request_counter += 1
    if _request_counter < _GC_EVERY:
        return
    _request_counter = 0
    cutoff = now - 60.0  # anything outside the sliding window is dead
    stale = [k for k, q in _buckets.items() if not q or q[-1] < cutoff]
    for k in stale:
        _buckets.pop(k, None)


# Hardcoded plan caps (requests/minute). Intentionally NOT env-configurable
# past the free tier so an over-eager env change can't accidentally rate-
# limit paid users.
PLAN_LIMITS: dict[str, int] = {
    "free":    30,
    "starter": 120,
    "pro":     300,
    "team":    600,
    "admin":   2000,
}


def _client_ip(request: Request) -> str:
    """Respect proxy headers for Railway / Replit / Fly."""
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client:
        return request.client.host
    return "unknown"


def _enabled() -> bool:
    return os.environ.get("RATE_LIMIT_ENABLED", "true").lower() == "true"


def _free_tier_override() -> int | None:
    """Env override for the free-tier ceiling. Ignored for paid plans."""
    v = os.environ.get("RATE_LIMIT_PER_MINUTE")
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def _resolve_identity(request: Request) -> tuple[str, str, int]:
    """
    Decide (bucket_key, plan, limit) for this request.

    We look up the signed-in user via the session cookie (handled upstream
    by main.py's _attach_user middleware — the result is on request.state.
    If not available yet, we decode the cookie directly here so this module
    can run before that middleware in the chain too.)
    """
    user = getattr(request.state, "user", None) if hasattr(request, "state") else None
    if user is None:
        try:
            from shared.auth.magic import verify_session_cookie, SESSION_COOKIE
            from shared.auth.users import get_user
            email = verify_session_cookie(request.cookies.get(SESSION_COOKIE))
            user = get_user(email) if email else None
        except Exception:
            user = None

    # Admin cookie = unlimited-ish tier
    try:
        from shared.admin import is_admin
        if is_admin(request):
            return f"admin:{_client_ip(request)}", "admin", PLAN_LIMITS["admin"]
    except Exception:
        pass

    if user and user.get("email"):
        plan = (user.get("plan") or "free").lower()
        limit = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
        if plan == "free":
            limit = _free_tier_override() or limit
        return f"user:{user['email']}", plan, limit

    plan = "anon"
    limit = _free_tier_override() or PLAN_LIMITS["free"]
    return f"ip:{_client_ip(request)}", plan, limit


async def rate_limit_middleware(request: Request, call_next):
    """Applies per-identity sliding window of 60s to API routes only."""
    if not _enabled():
        return await call_next(request)

    path = request.url.path
    if not (path.startswith("/api/")
            or path.startswith("/phronesis/api/")
            or path.startswith("/synthesis/api/")):
        return await call_next(request)
    if path == "/api/health":
        return await call_next(request)

    key, plan, limit = _resolve_identity(request)
    now = time.time()
    _maybe_gc_buckets(now)
    bucket = _buckets[key]
    window = 60.0

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
                "X-RateLimit-Tier": plan,
            },
            content={
                "error": "Rate limit exceeded. Try again in a few seconds.",
                "retry_after_seconds": retry_after,
                "tier": plan,
            },
        )

    bucket.append(now)
    remaining = max(0, limit - len(bucket))
    reset_at = int(bucket[0] + window) if bucket else int(now + window)

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(reset_at)
    response.headers["X-RateLimit-Tier"] = plan
    return response
