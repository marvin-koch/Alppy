"""One error envelope for the whole API.

Every failure — a raised ``ApiError``, a ``HTTPException`` from a dependency, a
Pydantic validation failure, or an unhandled exception — leaves the app in the
same shape:

```json
{"error": {"code": "not_found", "message": "class not found",
           "details": {...}, "request_id": "a1b2c3"}}
```

The frontend switches on ``code``; ``message`` is for the log and for a
developer, never for a teacher-facing string (those are localised client-side).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from alppy.core.logging import get_logger, request_id_var

log = get_logger(__name__)


class ApiError(Exception):
    """The only exception a handler should raise deliberately."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id_var.get(),
        }
    }


# --- Constructors. Named for the situation, not for the status code. -------
def not_found(resource: str, **details: Any) -> ApiError:
    """Also the answer to a cross-tenant read: a row in another school does not
    exist as far as this session is concerned. Never 403 — that would confirm
    the id."""
    return ApiError(status.HTTP_404_NOT_FOUND, "not_found", f"{resource} not found", details=details)


def unauthorized(message: str = "authentication required") -> ApiError:
    return ApiError(status.HTTP_401_UNAUTHORIZED, "unauthorized", message)


def forbidden(message: str) -> ApiError:
    return ApiError(status.HTTP_403_FORBIDDEN, "forbidden", message)


def conflict(message: str, *, code: str = "conflict", **details: Any) -> ApiError:
    """A 409. ``code`` is what the UI switches on, so a conflict the teacher can
    resolve — and each one is resolved differently — gets its own name rather
    than sharing a generic one with every other 409."""
    return ApiError(status.HTTP_409_CONFLICT, code, message, details=details)


def unprocessable(message: str, **details: Any) -> ApiError:
    return ApiError(
        422, "unprocessable", message, details=details
    )


def payload_too_large(message: str, **details: Any) -> ApiError:
    return ApiError(
        413, "payload_too_large", message, details=details
    )


def unsupported_media_type(message: str, **details: Any) -> ApiError:
    return ApiError(
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        "unsupported_media_type",
        message,
        details=details,
    )


def rate_limited(message: str, retry_after_s: int) -> ApiError:
    return ApiError(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "rate_limited",
        message,
        details={"retry_after_s": retry_after_s},
    )


def service_unavailable(message: str, **details: Any) -> ApiError:
    """A collaborating module is not deployed yet. Explicit, never a 500."""
    return ApiError(
        status.HTTP_503_SERVICE_UNAVAILABLE, "service_unavailable", message, details=details
    )


_STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "unprocessable",
    429: "rate_limited",
    503: "service_unavailable",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        log.info("http.error", code=exc.code, status=exc.status_code, message=exc.message)
        headers: dict[str, str] = {}
        if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            headers["Retry-After"] = str(exc.details.get("retry_after_s", 60))
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.details),
            headers=headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_body(
                "validation_error",
                "request body failed validation",
                {"errors": _jsonable_errors(exc)},
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        log.error("http.unhandled", error=type(exc).__name__, exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body("internal_error", "unexpected server error"),
        )


def _jsonable_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Drop the ``ctx`` blob, which can hold non-serialisable exceptions."""
    out: list[dict[str, Any]] = []
    for err in exc.errors():
        out.append(
            {
                "loc": [str(p) for p in err.get("loc", ())],
                "msg": str(err.get("msg", "")),
                "type": str(err.get("type", "")),
            }
        )
    return out
