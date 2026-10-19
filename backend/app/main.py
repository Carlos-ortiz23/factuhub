"""FastAPI application factory.

The application is built by a factory instead of being instantiated at import
time: importing a module must never require environment variables or a
reachable database.

Run it with:

    uvicorn app.main:create_app --factory --reload
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.app_info import SERVICE_NAME, get_app_version
from app.core.config import Settings, get_settings

API_V1_PREFIX = "/api/v1"

API_DESCRIPTION = """
Bank reconciliation platform API.

The MVP reads financial data only. It never writes accounting entries, and it
never modifies imported source records.
"""


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

    app.include_router(api_router, prefix=API_V1_PREFIX)
    return app
