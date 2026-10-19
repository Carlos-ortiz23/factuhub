"""Health and readiness endpoints.

Kept free of authentication on purpose: orchestrators need them before any
credential exists. They expose no data beyond service identity and dependency
reachability.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.core.app_info import SERVICE_NAME, get_app_version
from app.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Reports that the API process is running. It never touches the database.",
)
async def read_health() -> HealthResponse:
    return HealthResponse(service=SERVICE_NAME, version=get_app_version())


@router.get(
    "/health/ready",
    summary="Readiness probe",
    description="Verifies that the API can reach PostgreSQL.",
    responses={
        200: {"model": ReadinessResponse, "description": "Database reachable"},
        503: {"model": ReadinessResponse, "description": "Database unreachable"},
    },
)
def read_readiness(session: Annotated[Session, Depends(get_db_session)]) -> JSONResponse:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        # Deliberately opaque: connection strings and driver errors must not
        # cross the API boundary.
        payload = ReadinessResponse(status="degraded", database="unreachable")
        return JSONResponse(status_code=503, content=payload.model_dump())

    payload = ReadinessResponse(status="ready", database="ok")
    return JSONResponse(status_code=200, content=payload.model_dump())
