"""FastAPI application factory."""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.api.v1.router import api_router
from app.utils.log_scrub import install_root_scrubber

settings = get_settings()

# Install the secret-scrubbing logging filter before any app logger emits
# its first record. The filter redacts `sk-ant-…` and a handful of other
# credential shapes from every `LogRecord` (msg, args, exc_text) so an
# accidentally-logged raw key never reaches stdout / a file handler /
# structured log output. Pydantic's `SecretStr` on `settings.anthropic_
# api_key` is the primary defense; this is belt-and-suspenders for the
# path where a third-party SDK exception or a future bug materialises
# the raw value. Idempotent — re-running at import is a no-op.
install_root_scrubber()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Job Aggregator Platform",
    version="0.1.1",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)


# ── Security headers ─────────────────────────────────────────────────────
# Baseline response hardening. The regression tester flagged (finding 19)
# that prod responses were missing CSP/HSTS/Permissions-Policy/cross-origin
# headers. We apply a conservative set on every response. We deliberately
# DO NOT set a strict CSP on HTML routes yet (the frontend is served from
# a separate origin/container and the SPA bundle's build hashes rotate),
# but we do set headers that are safe for JSON APIs. HSTS is only meaningful
# under HTTPS; a reverse proxy would normally add it, but including it here
# defends against misconfigured termination.
#
# Regression finding 219: X-Frame-Options, X-Content-Type-Options, and
# Referrer-Policy are ALSO emitted by the outer infra nginx at the http
# block (`infra/nginx/nginx.conf:40-43`). nginx's `add_header` does NOT
# replace headers present in the upstream response — it APPENDS — so
# every API response was shipping two copies, one of them conflicting
# (FastAPI "X-Frame-Options: DENY" vs nginx "X-Frame-Options: SAMEORIGIN").
# Per RFC 7034 + MDN, browsers differ on multi-valued XFO: Chrome picks
# the strictest, Firefox ignores both, Safari undocumented — so the same
# app served different clickjacking protections to different users.
#
# Canonical choice per the finding: the infra nginx layer owns XFO /
# XCTO / Referrer-Policy because those headers survive even if the
# backend container crashes or is replaced with a static error page.
# We KEEP HSTS, Permissions-Policy, COOP, CORP, CSP in FastAPI because
# nginx does not set those; they would disappear on header-dedupe
# without this middleware. In the same round, nginx.conf's XFO value
# changes SAMEORIGIN → DENY to align with the CSP `frame-ancestors
# 'none'` intent ("nobody can frame us"), removing the stale
# same-origin-framing policy ambiguity.
_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Permissions-Policy": (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
        "magnetometer=(), microphone=(), payment=(), usb=()"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
    # A conservative CSP suitable for JSON API responses. The SPA that
    # renders HTML is served separately by nginx with its own CSP.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            # Don't stomp a header that an endpoint set intentionally.
            response.headers.setdefault(name, value)
        return response


app.add_middleware(SecurityHeadersMiddleware)

# Session middleware for OAuth state
app.add_middleware(SessionMiddleware, secret_key=settings.jwt_secret, session_cookie="oauth_state")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_url, "http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router)


@app.get("/api/health")
async def health():
    """Public health check — auth-free, suitable for CI assertions and
    load-balancer probes.

    Regression finding 234: previously returned only `{status, version}`
    with no signal on whether AI features were configured. Deploy.yml
    couldn't tell from outside the VM whether the ANTHROPIC_API_KEY
    Secret had actually reached the running container — every deploy
    ran green even when the key never made it to .env. The
    `ai_configured` boolean here gives the post-deploy verify job a
    cheap auth-free assertion target: if the GitHub Secret is set but
    this returns False, the deploy script silently dropped the key
    (the old line-2 stdin bug fixed in ci-deploy.sh::persist_anthropic_
    key_from_stdin).

    Importantly we expose only the BOOLEAN state, never the key
    value/prefix/length — `bool(key)` doesn't leak anything an attacker
    couldn't already infer by hitting an AI endpoint and reading the
    503 vs 200 response.
    """
    # F234 hotfix: `app.config` exposes `get_settings()` (lru_cached
    # factory), not a module-level `settings`. Calling the factory is
    # the canonical access pattern across the codebase (every router
    # does `from app.config import get_settings; settings =
    # get_settings()`). The earlier Round 63 commit imported a
    # non-existent name and 500'd `/api/health` on every request —
    # which broke the deploy verify step + every load-balancer probe.
    from app.config import get_settings
    settings = get_settings()
    raw_key = (
        settings.anthropic_api_key.get_secret_value()
        if settings.anthropic_api_key
        else ""
    )

    # VM host-metrics availability — auth-free signal so deploy.yml's
    # post-deploy verify can catch a broken `/host` bind-mount or a
    # stalled cron the same way it catches a missing ANTHROPIC_API_KEY.
    # The 2026-04-17 outage was invisible for days because nothing
    # outside the admin-only /monitoring/vm endpoint reported on this
    # pipeline; surfacing the boolean here lets CI fail loudly instead.
    #
    # Wrapped in try/except so a transient failure (e.g. /host briefly
    # unmounted during a rolling restart) can never 500 the
    # load-balancer probe. False is the safe default — "available" is
    # only ever True when host_stats actually parses a real snapshot.
    vm_available = False
    vm_age_s: int | None = None
    try:
        from app.services.host_stats import get_vm_metrics
        m = get_vm_metrics()
        vm_available = bool(m.get("available"))
        vm_age_s = m.get("snapshot_age_seconds")
    except Exception:
        # Don't import logging at module top just for this branch — health
        # is hot-path and we want the import cost paid only when get_vm_metrics
        # explodes (rare, deploy-time only). Silent except so the public
        # health endpoint stays {status: ok} no matter what.
        pass

    return {
        "status": "ok",
        "version": "0.1.1",
        "ai_configured": bool(raw_key.strip()),
        "vm_metrics_available": vm_available,
        "vm_metrics_age_seconds": vm_age_s,
    }
