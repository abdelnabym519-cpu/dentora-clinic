"""Per-tenant request rate + concurrency guard.

Why this exists: every clinic shares one process, one DB pool
(``pool_size + max_overflow = 30``) and one disk. The existing slowapi
limits are IP-keyed and only cover public/unauthenticated surfaces —
and behind the documented Cloudflare → Nuxt SSR → backend chain all
real clients collapse to a handful of IPs, so IP buckets cannot tell
tenants apart. This middleware keys authenticated traffic by tenant
(``clinic_id`` from the verified JWT, no DB lookup) and sheds excess
load with ``429`` before a runaway tenant can saturate the pool and
degrade every other clinic.

Design notes (deliberate, match the shipped single-worker architecture):

* In-memory fixed-window counters + in-flight gauges, same posture as
  the agent guardrails (``app/core/agents/guardrails.py``). Correct for
  the shipped single-uvicorn-worker deployment; a multi-worker rollout
  would need a shared store (tracked in the resource-isolation doc).
* Mutations happen in synchronous sections only (no ``await`` between
  check and increment), so no lock is needed on the single event loop.
* ``/health``, ``/health/ready``, ``/docs``, ``/redoc`` and
  ``/openapi.json`` are exempt — probes and schema must never 429.
* Unauthenticated requests (no usable JWT) fall back to the client IP
  bucket, mirroring the slowapi behaviour for those surfaces.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Literal

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi.util import get_remote_address

from app.config import settings

_EXEMPT_PREFIXES = ("/health", "/docs", "/redoc", "/openapi.json")

_WINDOW_SECONDS = 60.0


def resolve_tenant_key(request: Request) -> str:
    """Return the rate-limit bucket for this request.

    ``clinic:<uuid>`` for a verifiable Bearer JWT carrying ``clinic_id``,
    ``user:<sub>`` for a verifiable JWT without one, otherwise the client
    IP (public surfaces, bad/expired tokens). Verification reuses the app
    secret; anything undecodable falls back to IP — fail-open to the
    coarser bucket, never fail-closed.
    """
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        try:
            from app.core.auth.service import decode_token

            payload = decode_token(token.strip())
        except Exception:
            payload = None
        if payload:
            clinic_id = payload.get("clinic_id")
            if clinic_id:
                return f"clinic:{clinic_id}"
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
    return f"ip:{get_remote_address(request)}"


# Fixed-window timestamps per bucket and in-flight gauges. Module-level
# on purpose (see module docstring); tests reset via ``reset_state``.
_windows: dict[str, deque[float]] = {}
_inflight: dict[str, int] = {}


def reset_state() -> None:
    """Clear all counters. Tests only."""
    _windows.clear()
    _inflight.clear()


@dataclass
class Verdict:
    allowed: bool
    reason: Literal["ok", "rate", "concurrency"] = "ok"
    retry_after: int = 0


def check_and_acquire(key: str, *, now: float | None = None) -> Verdict:
    """Apply the rate window and the concurrency gauge for ``key``.

    On ``allowed`` the caller MUST eventually call :func:`release` (in a
    ``finally``) or the gauge leaks and the tenant is throttled forever.
    """
    if not settings.TENANT_LIMITS_ENABLED:
        return Verdict(allowed=True)
    now = time.monotonic() if now is None else now

    window = _windows.get(key)
    if window is None:
        window = deque()
        _windows[key] = window
    while window and now - window[0] > _WINDOW_SECONDS:
        window.popleft()
    if len(window) >= settings.TENANT_MAX_REQUESTS_PER_MINUTE:
        retry_after = max(1, int(_WINDOW_SECONDS - (now - window[0])))
        return Verdict(allowed=False, reason="rate", retry_after=retry_after)

    if _inflight.get(key, 0) >= settings.TENANT_MAX_CONCURRENT_REQUESTS:
        return Verdict(allowed=False, reason="concurrency")

    window.append(now)
    _inflight[key] = _inflight.get(key, 0) + 1
    return Verdict(allowed=True)


def release(key: str) -> None:
    """Return one in-flight slot. Always call from ``finally``."""
    current = _inflight.get(key, 0)
    if current <= 1:
        _inflight.pop(key, None)
    else:
        _inflight[key] = current - 1


def _is_exempt(path: str) -> bool:
    return path == "/" or path.startswith(_EXEMPT_PREFIXES)


def _cors_headers(request: Request) -> dict[str, str]:
    """Same CORS reflection as ``app.main`` so 429s stay browser-readable."""
    origin = request.headers.get("origin")
    if not origin:
        return {}
    allowed = settings.allowed_origins_list
    if settings.ENVIRONMENT == "development":
        allowed = allowed + [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        ]
    if origin in allowed or "*" in allowed:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Vary": "Origin",
        }
    return {}


def _too_many(request: Request, verdict: Verdict) -> JSONResponse:
    if verdict.reason == "rate":
        message = (
            "Tenant request rate exceeded; slow down and retry. "
            "If this is legitimate load, raise TENANT_MAX_REQUESTS_PER_MINUTE."
        )
    else:
        message = (
            "Tenant concurrency limit exceeded; too many requests in flight. "
            "If this is legitimate load, raise TENANT_MAX_CONCURRENT_REQUESTS."
        )
    headers = _cors_headers(request)
    if verdict.retry_after:
        headers["Retry-After"] = str(verdict.retry_after)
    return JSONResponse(
        status_code=429,
        content={"data": None, "message": message, "errors": [message]},
        headers=headers,
    )


async def tenant_limits_middleware(request: Request, call_next):
    """FastAPI ``@app.middleware("http")`` entry point (see ``app.main``)."""
    if not settings.TENANT_LIMITS_ENABLED or _is_exempt(request.url.path):
        return await call_next(request)
    key = resolve_tenant_key(request)
    verdict = check_and_acquire(key)
    if not verdict.allowed:
        return _too_many(request, verdict)
    try:
        return await call_next(request)
    finally:
        release(key)
