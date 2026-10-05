from typing import cast

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import get_request_id

logger = structlog.get_logger(__name__)


class FinTrackError(Exception):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    code = "INTERNAL_ERROR"
    message = "An unexpected error occurred"

    def __init__(self, message: str | None = None, *, code: str | None = None) -> None:
        self.message = message or self.message
        self.code = code or self.code
        super().__init__(self.message)


class NotFoundError(FinTrackError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"
    message = "The requested resource was not found"


class ConflictError(FinTrackError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"
    message = "The request conflicts with the current state of the resource"


class BusinessRuleError(FinTrackError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "BUSINESS_RULE_VIOLATION"
    message = "The request violates a business rule"


class UnprocessableEntityError(FinTrackError):
    """For a request that is well-formed and individually-valid-field-by-field but whose
    fields don't make sense together (e.g. transferring an account to itself) - distinct
    from BusinessRuleError (400), matching the 422 codes named in docs/api-design.md.
    """

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "UNPROCESSABLE_ENTITY"
    message = "The request could not be processed"


class UnauthorizedError(FinTrackError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHORIZED"
    message = "Authentication is required"


class ForbiddenError(FinTrackError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"
    message = "You do not have permission to perform this action"


class RateLimitedError(FinTrackError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMITED"
    message = "Too many requests"


class GoneError(FinTrackError):
    status_code = status.HTTP_410_GONE
    code = "GONE"
    message = "This resource is no longer available"


class PayloadTooLargeError(FinTrackError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = "PAYLOAD_TOO_LARGE"
    message = "The uploaded file is too large"


def error_body(
    code: str, message: str, details: list[dict[str, str]] | None = None
) -> dict[str, object]:
    error: dict[str, object] = {"code": code, "message": message, "request_id": get_request_id()}
    if details:
        error["details"] = details
    return {"error": error}


async def _fintrack_error_handler(_: Request, exc: Exception) -> JSONResponse:
    # Registered via add_exception_handler(FinTrackError, ...), so this is always the real type.
    error = cast(FinTrackError, exc)
    return JSONResponse(
        status_code=error.status_code, content=error_body(error.code, error.message)
    )


async def _validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    error = cast(RequestValidationError, exc)
    details = [
        {"field": ".".join(str(part) for part in err["loc"]), "message": str(err["msg"])}
        for err in error.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=error_body("VALIDATION_ERROR", "Request validation failed", details),
    )


async def _http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    error = cast(StarletteHTTPException, exc)
    code = "NOT_FOUND" if error.status_code == status.HTTP_404_NOT_FOUND else "HTTP_ERROR"
    return JSONResponse(
        status_code=error.status_code,
        content=error_body(code, str(error.detail)),
        headers=error.headers,
    )


async def _unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled_exception", exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_body("INTERNAL_ERROR", "An unexpected error occurred"),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(FinTrackError, _fintrack_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
