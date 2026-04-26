"""FastAPI application factory."""

import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.api.v1.router import api_router
from app.utils.log_scrub import install_root_scrubber

logger = logging.getLogger(__name__)

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


async def _seed_remote_companies_if_enabled() -> None:
    """F246(b) regression fix — startup-time idempotent seed of the
    synthetic platform boards (HN "Who is Hiring?", YC Work at a Startup,
    plus the long-standing aggregators like RemoteOK/Remotive).

    WHY THIS RUNS HERE
    ------------------
    F246(a) added a ``python -m app.seed_remote_companies`` invocation
    to ``ci-deploy.sh`` after ``alembic upgrade head``. That should
    have shipped the seed on every deploy. Live verification on
    2026-04-26 showed prod still had **0 hackernews + 0 yc_waas
    boards** despite multiple deploys with the new ci-deploy.sh —
    the deploy-shell step either silently failed, ran against the
    wrong DB, or never executed (no shell access to the VM means we
    couldn't tell which). Symptom: Track B fetchers register cleanly
    but every scheduled scan tick is a no-op against zero boards.

    Running the seed inside the FastAPI ``lifespan`` makes it
    effectively unconditional — every backend container boot
    re-applies the seed, so prod converges to the correct state on
    the first restart after this commit lands. The seed module is
    fully idempotent (check-then-insert against ``companies.name``
    and the ``(company_id, platform, slug)`` triple), so re-running
    on every boot adds only the genuinely-new rows.

    Failure is non-fatal: the existing platform-boards corpus is
    already correct for the legacy 14 platforms, and Track B is
    a feature gap, not a crash surface. We log the failure so it's
    visible in container logs but DO NOT block the rest of the
    lifespan from yielding (which would break the /api/health probe
    and trigger a docker-compose restart loop).

    Opt-out via env var ``SEED_REMOTE_COMPANIES_ON_STARTUP=0`` for
    test fixtures + local dev where the DB is intentionally empty.
    """
    if os.environ.get("SEED_REMOTE_COMPANIES_ON_STARTUP", "1") == "0":
        return
    try:
        from app.seed_remote_companies import seed_remote
        await seed_remote()
        logger.info("startup-seed: seed_remote_companies completed")
    except Exception as exc:
        logger.warning(
            "startup-seed: seed_remote_companies failed (non-fatal): %s",
            exc,
            exc_info=True,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _seed_remote_companies_if_enabled()
    yield


app = FastAPI(
    title="Job Aggregator Platform",
    version="0.1.1",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    # F242(c) regression fix: keep the OpenAPI spec under the ``/api``
    # prefix that nginx proxies to the backend. Pre-fix, ``docs_url``
    # and ``redoc_url`` were prefixed but ``openapi_url`` defaulted to
    # ``/openapi.json``. In prod, nginx's ``/api/*`` rule routes to the
    # backend while ``/openapi.json`` (no ``/api`` prefix) fell through
    # to the React SPA — Swagger loaded the HTML shell, then the
    # ``url: '/openapi.json'`` reference returned the index.html bundle,
    # and the browser console showed ``Failed to load API definition``.
    # Aligning the OpenAPI URL with the docs prefix means EVERY OpenAPI
    # consumer (Swagger UI, ReDoc, third-party clients pointed at the
    # spec) sees the JSON spec without infra changes.
    openapi_url="/api/openapi.json",
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
    # get_settings()`). An earlier Round 63 commit imported a
    # non-existent name and 500'd `/api/health` on every request —
    # which broke the deploy verify step + every load-balancer probe.
    # This is the corrected version (Merge conflict resolved by taking
    # HEAD wholesale — the feat branch had the pre-hotfix broken code).
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
