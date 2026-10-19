"""FastAPI application factory.

The application is built by a factory instead of being instantiated at import
time: importing a module must never require environment variables or a
reachable database.

Run it with:

    uvicorn app.main:create_app --factory --reload
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.app_info import SERVICE_NAME, get_app_version
from app.core.config import Settings, get_settings

API_V1_PREFIX = "/api/v1"

API_DESCRIPTION = """
Bank reconciliation platform API.

The MVP reads financial data only. It never writes accounting entries, and it
never modifies imported source records.
"""

#: Error keys that repeat the submitted value. FastAPI includes them by default;
#: this API never does, because one of its request bodies is a credential.
#: `ctx` can also carry a Python exception object, which is not JSON-serializable.
UNSAFE_VALIDATION_ERROR_KEYS = frozenset({"input", "ctx", "url"})


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application with explicit dependencies."""
    resolved_settings = settings or get_settings()

    app = FastAPI(
        title="FactuHub API",
        version=get_app_version(),
        description=API_DESCRIPTION,
    )
    # Settings are attached to the app state so request-scoped dependencies can
    # read them without importing module-level globals.
    app.state.settings = resolved_settings
    app.state.service_name = SERVICE_NAME

    @app.exception_handler(RequestValidationError)
    async def _validation_error_without_input(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Answer 422 without echoing what the caller sent.

        The default body repeats the offending value under `input`. That is
        tolerable for a page size and unacceptable for an API key: the value
        would land in the response, and in any proxy that logs response bodies.
        What the caller needs is which field is wrong and why, not their own
        secret read back to them.
        """
        detail = [
            {key: value for key, value in error.items() if key not in UNSAFE_VALIDATION_ERROR_KEYS}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"detail": detail},
        )

    app.include_router(api_router, prefix=API_V1_PREFIX)
    return app
