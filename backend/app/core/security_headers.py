"""Baseline security response headers for every API response.

The API serves JSON plus authenticated file downloads (patient documents,
thumbnails). Without hardening headers, browsers may MIME-sniff a crafted
upload served with an attacker-influenced ``Content-Type`` (``nosniff``
gap), embed an authenticated response in a third-party frame
(clickjacking), or leak full internal URLs (ids, slugs) to external sites
via ``Referer``. These three headers are behavior-neutral for API clients
(SDKs, the Nuxt frontend, Swagger in dev) and close the residual risk that
per-endpoint fixes alone cannot cover.
"""

from fastapi import Request


async def security_headers_middleware(request: Request, call_next):  # noqa: ANN001, ANN201
    """Attach baseline security headers to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    return response
