"""API dependency factories."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from datapilot.adapters.database import PostgresAnalysisRunRepository, PostgresAnalyticsDatabase
from datapilot.config import Settings, get_settings
from datapilot.policies.sql_safety import SQLSafetyPolicy
from datapilot.services.agent import AnalysisAgent

SettingsDependency = Annotated[Settings, Depends(get_settings)]


def get_sql_safety_policy(settings: SettingsDependency) -> SQLSafetyPolicy:
    return SQLSafetyPolicy(
        dialect=settings.sql_dialect,
        max_rows=settings.sql_max_rows,
        enabled=settings.sql_safety_enabled,
        allowed_schemas=frozenset(settings.sql_allowed_schemas),
    )


SQLSafetyPolicyDependency = Annotated[SQLSafetyPolicy, Depends(get_sql_safety_policy)]


def get_analytics_database(request: Request) -> PostgresAnalyticsDatabase:
    database = getattr(request.app.state, "analytics_database", None)
    if not isinstance(database, PostgresAnalyticsDatabase):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The analytics database is not configured.",
        )
    return database


AnalyticsDatabaseDependency = Annotated[
    PostgresAnalyticsDatabase,
    Depends(get_analytics_database),
]


def require_query_api(settings: SettingsDependency) -> None:
    if not settings.enable_query_api:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The query API is disabled.",
        )


QueryAPIEnabledDependency = Annotated[None, Depends(require_query_api)]


def get_analysis_agent(request: Request) -> AnalysisAgent:
    agent = getattr(request.app.state, "analysis_agent", None)
    if not isinstance(agent, AnalysisAgent):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The analysis agent is not configured.",
        )
    return agent


AnalysisAgentDependency = Annotated[AnalysisAgent, Depends(get_analysis_agent)]


def require_agent_api(settings: SettingsDependency) -> None:
    if not settings.enable_agent_api:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The analysis agent API is disabled.",
        )


AgentAPIEnabledDependency = Annotated[None, Depends(require_agent_api)]


def get_analysis_run_repository(request: Request) -> PostgresAnalysisRunRepository:
    repository = getattr(request.app.state, "analysis_run_repository", None)
    if not isinstance(repository, PostgresAnalysisRunRepository):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analysis run history is not configured.",
        )
    return repository


AnalysisRunRepositoryDependency = Annotated[
    PostgresAnalysisRunRepository,
    Depends(get_analysis_run_repository),
]
