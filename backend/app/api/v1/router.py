"""Version 1 of the HTTP API."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import accounting_providers, auth, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(accounting_providers.router)
