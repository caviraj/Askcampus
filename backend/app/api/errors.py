"""One error shape for the whole API.

Every non-2xx response is an ErrorResponse, so the frontend has a single thing
to parse. Copy follows DESIGN_SYSTEM.md section 9: state what happened and the
next action, never apologize.
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.common import ErrorResponse

# Used for exceptions we did not raise ourselves, e.g. Starlette's 404 for an
# unknown path or 405 for a wrong method.
_FALLBACK_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


class ApiError(HTTPException):
    """An HTTPException that carries a machine-readable code."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code


async def api_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = getattr(exc, "code", None) or _FALLBACK_CODES.get(exc.status_code, "error")
    detail = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(detail=detail, code=code).model_dump(),
        headers=getattr(exc, "headers", None),
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # The raw pydantic errors are not sent to the client: they describe internal
    # field names, and the frontend shows its own per-field messages.
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            detail="The request was not valid. Check the fields and try again.",
            code="validation_error",
        ).model_dump(),
    )
