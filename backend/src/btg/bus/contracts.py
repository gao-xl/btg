"""Versioned REST response and error contracts shared by BTG APIs.

Handlers must return :func:`success` or raise :class:`APIError`; applications
must call :func:`install_exception_handlers` once during startup.
"""
from __future__ import annotations

import time
from typing import Any, Generic, Literal, TypeVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException


T = TypeVar("T")


class ResponseEnvelope(BaseModel, Generic[T]):
    """The only successful REST response shape exposed by BTG."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["success"] = "success"
    code: int = Field(ge=200, lt=300)
    timestamp: float = Field(default_factory=time.time)
    data: T


class ErrorDetail(BaseModel):
    """Machine-readable failure details without leaking implementation traces."""

    model_config = ConfigDict(extra="forbid")

    type: str
    message: str
    details: list[dict[str, Any]] | None = None


class ErrorEnvelope(BaseModel):
    """The only REST error response shape exposed by BTG."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["error"] = "error"
    code: int = Field(ge=400, lt=600)
    timestamp: float = Field(default_factory=time.time)
    error: ErrorDetail


class APIError(Exception):
    """Expected API failure represented by the public BTG error contract."""

    def __init__(
        self,
        status_code: int,
        error_type: str,
        message: str,
        *,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        self.status_code = status_code
        self.error_type = error_type
        self.message = message
        self.details = details
        super().__init__(message)


def success(data: T, *, status_code: int = 200) -> ResponseEnvelope[T]:
    """Build a validated successful response envelope."""
    return ResponseEnvelope(code=status_code, data=data)


def _error_response(
    status_code: int,
    error_type: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    body = ErrorEnvelope(
        code=status_code,
        error=ErrorDetail(type=error_type, message=message, details=details),
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=True))


def install_exception_handlers(app: FastAPI) -> None:
    """Install the required contract-preserving exception handlers on *app*."""

    @app.exception_handler(APIError)
    async def handle_api_error(_: Request, exc: APIError) -> JSONResponse:
        return _error_response(exc.status_code, exc.error_type, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(422, "validation_error", "Request validation failed.", exc.errors())

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return _error_response(exc.status_code, "http_error", message)