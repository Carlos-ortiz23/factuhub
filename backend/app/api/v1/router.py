"""Version 1 of the HTTP API."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import (
    accounting_providers,
    auth,
    connections,
    health,
    imports,
    organizations,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(connections.router)
api_router.include_router(accounting_providers.router)
api_router.include_router(imports.router)
