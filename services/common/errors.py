"""
Unified error handling for all services.

Provides consistent error response format and global exception handlers.
"""

import traceback
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError


ERROR_RESPONSE_TEMPLATE = {
    "error": {
        "code": "",
        "message": "",
        "details": None,
    },
    "request_id": "",
}


def setup_error_handlers(app: FastAPI, service_name: str = ""):
    """Register global exception handlers on a FastAPI app."""

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": f"HTTP_{exc.status_code}",
                    "message": exc.detail,
                    "details": None,
                },
                "service": service_name,
                "path": str(request.url.path),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "details": exc.errors(),
                },
                "service": service_name,
                "path": str(request.url.path),
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(exc),
                    "details": traceback.format_exc().split("\n")[-5:] if app.debug else None,
                },
                "service": service_name,
                "path": str(request.url.path),
            },
        )
