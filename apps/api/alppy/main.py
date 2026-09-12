"""FastAPI application factory.

``create_app`` is a function, not a module-level singleton, so the test suite
can build an app against an in-memory database without importing a Postgres
driver, and so settings are read once per app rather than once per process.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from alppy.api.errors import install_error_handlers
from alppy.api.v1 import api_router
from alppy.core.config import Settings, get_settings
from alppy.core.logging import configure_logging, get_logger, new_request_id, request_id_var

log = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

#: A caller may name their own request id so a trace spans their system and
#: ours, but the value is echoed into every log line and every error envelope.
#: Unconstrained, a newline in it forges log entries in whatever aggregator
#: reads them. Anything that is not a plain token is replaced rather than
#: rejected: the header is a convenience, and failing a request over it would
#: turn a cosmetic problem into an outage.
_REQUEST_ID_RE = re.compile(r"\A[A-Za-z0-9._-]{1,64}\Z")

# Set on every response, including the ones that are not JSON.
#
# Two of this API's routes hand a browser something it will render: the sheet
# preview (`GET /sheets/{id}/preview`, framed by the builder) and `/files/`,
# which serves teacher-uploaded exercise figures and scanned pages straight
# from the object store. `nosniff` is what stops a file uploaded as a figure
# being interpreted as script — `api/v1/health.py` already reasoned about it
# being set, and it was not.
#
# The web app sets its own, richer policy in `apps/web/src/middleware.ts`;
# these cover the API when it is reached directly rather than through it.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


def frame_ancestors(settings: Settings) -> str:
    """Who may frame the preview: us, and the front ends we are configured for.

    `frame-ancestors 'self'` was deliberately not `'none'` because the preview
    is *supposed* to be framed by the builder — but `'self'` is the API's OWN
    origin, and the builder is not served from it. Under one reverse proxy
    that is the same origin and the policy was right; under the arrangement
    this repository actually ships — `docker compose up`, web on :3000 and API
    on :8000, and `next.config.ts`'s "in development the API runs on its own
    port" — it is a different origin, so the browser refused every preview and
    the builder's preview panel and the sheet screen's two tabs were blank with
    the only explanation in the console.

    `cors_origins` is the list of front ends this API is configured to trust
    with a credentialed request, which is a strictly stronger trust than being
    allowed to frame one HTML page. Reusing it keeps the two from drifting;
    naming the origins again in a second variable is how they would.

    A wildcard is dropped rather than translated. `_refuse_unsafe_deployment`
    already refuses one in staging and production, and `frame-ancestors *` is
    the clickjacking hole this header exists to close — so on a local instance
    that permits `"*"` for CORS, framing still falls back to `'self'` alone.
    """
    origins = [origin for origin in settings.cors_origins if "*" not in origin]
    return " ".join(["frame-ancestors", "'self'", *origins])

DESCRIPTION = """
Alppy — teacher-facing tooling for Swiss compulsory school (Sek I, cycle 3).

Every endpoint below `/api/v1` except `/auth/login` and `/health` requires a
session cookie, and every scoped query filters on the school resolved from it.
"""


def _install_request_id(app: FastAPI, settings: Settings) -> None:
    csp = frame_ancestors(settings)
    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming if incoming and _REQUEST_ID_RE.match(incoming) else new_request_id()
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            for header, value in SECURITY_HEADERS.items():
                response.headers.setdefault(header, value)
            response.headers.setdefault("Content-Security-Policy", csp)
            log.info(
                "http.request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            return response
        finally:
            # Reset last, so both the access line above and any error
            # envelope built downstream carry this request's id.
            request_id_var.reset(token)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    configure_logging(debug=resolved.debug)

    # The schema is a development tool, and it was served to anyone who asked,
    # in every environment. It exposes no data, but it is the map: every route,
    # every field name, every enum value and every validation bound, offered to
    # an unauthenticated reader ahead of any attempt on the endpoints
    # themselves. Nothing needs it in a real deployment — the shared types are
    # generated in the repository, not fetched from a running server — so the
    # routes are simply not mounted there. `local` and `ci` keep them: the
    # schema is how the web app's client is checked against the API.
    #
    # Same test as the session cookie's `secure` flag (`api/v1/auth.py`), and
    # deliberately the same one: both say "this is a real deployment".
    is_deployment = resolved.env in ("staging", "production")

    app = FastAPI(
        title="Alppy API",
        version="1.0.0",
        description=DESCRIPTION,
        # `docs_url` alone would not be enough: Swagger UI is only the reader,
        # and `openapi.json` is the document. Dropping the document drops both,
        # and FastAPI refuses to mount the UI without it.
        openapi_url=None if is_deployment else "/api/v1/openapi.json",
        docs_url=None if is_deployment else "/api/v1/docs",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )
    _install_request_id(app, resolved)
    install_error_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
