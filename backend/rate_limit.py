"""Small process-local request limiter for single-instance deployments."""

from collections import defaultdict, deque
import hashlib
import threading
import time

from fastapi import Request
from fastapi.responses import JSONResponse

from .config import (
    AI_REQUESTS_PER_MINUTE,
    AUTH_REQUESTS_PER_MINUTE,
    GENERAL_REQUESTS_PER_MINUTE,
)


_LOCK = threading.Lock()
_BUCKETS: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_LAST_PRUNE = 0.0


def _identity(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if authorization.casefold().startswith("bearer "):
        return hashlib.sha256(authorization.encode("utf-8")).hexdigest()
    return request.client.host if request.client else "unknown"


def _category(request: Request) -> tuple[str, int]:
    path = request.url.path
    if path in {"/auth/login", "/auth/register"}:
        return "auth", AUTH_REQUESTS_PER_MINUTE
    if request.method == "POST" and (
        path == "/chat" or path == "/summary" or path.startswith("/quiz")
    ):
        return "ai", AI_REQUESTS_PER_MINUTE
    return "general", GENERAL_REQUESTS_PER_MINUTE


async def rate_limit_middleware(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path == "/health":
        return await call_next(request)
    now = time.monotonic()
    category, limit = _category(request)
    key = (_identity(request), category)
    global _LAST_PRUNE
    with _LOCK:
        bucket = _BUCKETS[key]
        while bucket and bucket[0] <= now - 60:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, round(60 - (now - bucket[0])))
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please wait and try again."},
                headers={"Retry-After": str(retry_after)},
            )
        bucket.append(now)
        if now - _LAST_PRUNE > 300:
            stale = [
                bucket_key
                for bucket_key, values in _BUCKETS.items()
                if not values or values[-1] <= now - 60
            ]
            for bucket_key in stale:
                _BUCKETS.pop(bucket_key, None)
            _LAST_PRUNE = now
    return await call_next(request)
