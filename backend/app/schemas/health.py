"""Transport contracts for health and readiness probes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

DatabaseStatus = Literal["ok", "unreachable"]


class HealthResponse(BaseModel):
    """Liveness answer: the process is up and serving requests."""

    status: Literal["ok"] = "ok"
    service: str
    version: str


class ReadinessResponse(BaseModel):
    """Readiness answer: the process can reach its critical dependency."""

    status: Literal["ready", "degraded"]
    database: DatabaseStatus
