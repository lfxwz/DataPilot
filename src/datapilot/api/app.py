"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from datapilot import __version__
from datapilot.adapters.database import PostgresAnalysisRunRepository, PostgresAnalyticsDatabase
from datapilot.adapters.llm import OpenAICompatibleClient
from datapilot.adapters.sandbox import DockerSandboxExecutor
from datapilot.api.routes import agent, analysis, health, schema, sql
from datapilot.config import Settings, get_settings
from datapilot.policies.sql_safety import SQLSafetyPolicy
from datapilot.services.agent import AnalysisAgent
from datapilot.services.credentials import resolve_llm_api_key
from datapilot.telemetry.logging import configure_logging

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an isolated app instance suitable for production and tests."""

    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_logging(app_settings.log_level)
        database: PostgresAnalyticsDatabase | None = None
        llm: OpenAICompatibleClient | None = None
        analysis_agent: AnalysisAgent | None = None
        run_repository: PostgresAnalysisRunRepository | None = None
        policy = SQLSafetyPolicy(
            dialect=app_settings.sql_dialect,
            max_rows=app_settings.sql_max_rows,
            enabled=app_settings.sql_safety_enabled,
            allowed_schemas=frozenset(app_settings.sql_allowed_schemas),
        )
        if app_settings.database_url is not None:
            database = PostgresAnalyticsDatabase(
                app_settings.database_url.get_secret_value(),
                policy=policy,
                statement_timeout_ms=app_settings.sql_statement_timeout_ms,
                max_estimated_cost=app_settings.sql_max_estimated_cost,
            )
        if app_settings.metadata_database_url is not None:
            run_repository = PostgresAnalysisRunRepository(
                app_settings.metadata_database_url.get_secret_value()
            )
        if app_settings.enable_agent_api and app_settings.llm_is_configured and database:
            assert app_settings.llm_base_url is not None
            assert app_settings.llm_model is not None
            llm = OpenAICompatibleClient(
                base_url=app_settings.llm_base_url,
                api_key=resolve_llm_api_key(app_settings),
                model=app_settings.llm_model,
                timeout_seconds=app_settings.llm_timeout_seconds,
                max_retries=app_settings.llm_max_retries,
                thinking_enabled=app_settings.llm_thinking_enabled,
            )
            analysis_agent = AnalysisAgent(
                database=database,
                llm=llm,
                policy=policy,
                model_name=app_settings.llm_model,
                schema_names=app_settings.sql_allowed_schemas,
                max_sql_retries=app_settings.sql_max_retries,
                generated_code_executor=(
                    DockerSandboxExecutor(
                        container_name=app_settings.sandbox_container_name,
                        timeout_seconds=app_settings.sandbox_timeout_seconds,
                        memory_mb=app_settings.sandbox_memory_mb,
                        cpu_count=app_settings.sandbox_cpu_count,
                    )
                    if app_settings.enable_generated_python
                    else None
                ),
                run_repository=run_repository,
            )
        app.state.analytics_database = database
        app.state.analysis_agent = analysis_agent
        app.state.analysis_run_repository = run_repository
        logger.info(
            "application_started",
            extra={"service": "datapilot-api", "version": __version__},
        )
        yield
        if database is not None:
            database.close()
        if run_repository is not None:
            run_repository.close()
        if llm is not None:
            llm.close()
        logger.info("application_stopped", extra={"service": "datapilot-api"})

    app = FastAPI(
        title="DataPilot API",
        description="Auditable SQL, verified Python, and isolated generated analytics.",
        version=__version__,
        docs_url="/docs" if app_settings.environment != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.dependency_overrides[get_settings] = lambda: app_settings
    if app_settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(app_settings.cors_allowed_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-Request-ID"],
        )

    @app.middleware("http")
    async def correlate_request(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))[:128]
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(agent.router, prefix="/api/v1")
    app.include_router(analysis.router, prefix="/api/v1")
    app.include_router(schema.router, prefix="/api/v1")
    app.include_router(sql.router, prefix="/api/v1")
    return app
