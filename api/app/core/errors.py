"""Single error contract. Every non-2xx response uses this envelope."""

import logging
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import current_request_id

logger = logging.getLogger("gapfinder.errors")

ErrorCode = Literal[
    "UNAUTHENTICATED",
    "FORBIDDEN",
    "NOT_FOUND",
    "VALIDATION_ERROR",
    "INVALID_STATE",
    "PROCESSING",
    "INSUFFICIENT_WORKSPACE_EVIDENCE",
    "RATE_LIMITED",
    "PROVIDER_UNAVAILABLE",
    "FILE_TOO_LARGE",
    "INTERNAL_ERROR",
]
NextAction = Literal["none", "upload_or_select_material", "retry", "sign_in"]


class ErrorDetail(BaseModel):
    code: str
    message: str
    requestId: str
    retryable: bool = False
    nextAction: NextAction = "none"


class AppError(Exception):
    """Raise from routes/services; translated into the error envelope by the handler."""

    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        next_action: NextAction = "none",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.next_action = next_action


def not_found(what: str = "Resource") -> AppError:
    return AppError(404, "NOT_FOUND", f"{what} was not found.")


def invalid_state(message: str) -> AppError:
    return AppError(409, "INVALID_STATE", message)


def provider_unavailable(message: str) -> AppError:
    return AppError(503, "PROVIDER_UNAVAILABLE", message, retryable=True, next_action="retry")


def envelope(
    status_code: int,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    next_action: NextAction = "none",
) -> JSONResponse:
    request_id = current_request_id()
    return JSONResponse(
        status_code=status_code,
        content={
            "error": ErrorDetail(
                code=code,
                message=message,
                requestId=request_id,
                retryable=retryable,
                nextAction=next_action,
            ).model_dump()
        },
        headers={"x-request-id": request_id},
    )


_STATUS_CODES: dict[int, ErrorCode] = {
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "VALIDATION_ERROR",
    409: "INVALID_STATE",
    413: "FILE_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    503: "PROVIDER_UNAVAILABLE",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, error: AppError) -> JSONResponse:
        return envelope(
            error.status_code,
            error.code,
            error.message,
            retryable=error.retryable,
            next_action=error.next_action,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, error: RequestValidationError) -> JSONResponse:
        fields = sorted(
            {".".join(str(p) for p in item.get("loc", ())[1:]) for item in error.errors()}
        )
        detail = f" Check: {', '.join(f for f in fields if f)}." if fields else ""
        return envelope(422, "VALIDATION_ERROR", f"The request is invalid.{detail}")

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, error: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(error.status_code, "INTERNAL_ERROR")
        message = error.detail if isinstance(error.detail, str) else "The request failed."
        return envelope(
            error.status_code,
            code,
            message,
            next_action="sign_in" if code == "UNAUTHENTICATED" else "none",
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, error: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=error)
        return envelope(500, "INTERNAL_ERROR", "Something went wrong.", retryable=True)
