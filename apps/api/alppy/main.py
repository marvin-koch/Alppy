"""FastAPI application factory.

``create_app`` is a function, not a module-level singleton, so the test suite
can build an app against an in-memory database without importing a Postgres
driver, and so settings are read once per app rather than once per process.
"""

from __future__ import annotations

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

DESCRIPTION = """
Alppy — teacher-facing tooling for Swiss compulsory school (Sek I, cycle 3).

Every endpoint below `/api/v1` except `/auth/login` and `/health` requires a
session cookie, and every scoped query filters on the school resolved from it.
"""


def _install_request_id(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming if incoming and len(incoming) <= 64 else new_request_id()
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
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
    _install_request_id(app)
    install_error_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
