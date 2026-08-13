"""Liveness and configuration-aware readiness endpoints."""

from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict

from datapilot import __version__
from datapilot.api.dependencies import SettingsDependency

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "not_ready"]
    service: str
    version: str
    environment: str
    checks: dict[str, bool]


@router.get("/live", response_model=HealthResponse)
def liveness(settings: SettingsDependency) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="datapilot-api",
        version=__version__,
        environment=settings.environment,
        checks={"process": True},
    )


@router.get("/ready", response_model=HealthResponse)
def readiness(
    response: Response,
    settings: SettingsDependency,
) -> HealthResponse:
    """Report dependency configuration without opening external connections."""

    database_configured = settings.database_url is not None
    if not database_configured:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if database_configured else "not_ready",
        service="datapilot-api",
        version=__version__,
        environment=settings.environment,
        checks={
            "process": True,
            "database_configured": database_configured,
            "llm_configured": settings.llm_is_configured,
            "metadata_database_configured": settings.metadata_is_configured,
        },
    )
