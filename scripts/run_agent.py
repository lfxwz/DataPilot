"""Run one DataPilot analysis directly from the command line."""

from __future__ import annotations

import argparse

from datapilot.adapters.database import PostgresAnalysisRunRepository, PostgresAnalyticsDatabase
from datapilot.adapters.llm import OpenAICompatibleClient
from datapilot.adapters.sandbox import DockerSandboxExecutor
from datapilot.config import Settings
from datapilot.domain.analysis import AnalysisRequest
from datapilot.policies.sql_safety import SQLSafetyPolicy
from datapilot.services.agent import AnalysisAgent
from datapilot.services.credentials import resolve_llm_api_key


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ask a natural-language question of the configured read-only database."
    )
    parser.add_argument("question", help="The analytical question to investigate.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = Settings()
    if settings.database_url is None:
        raise SystemExit("DATAPILOT_DATABASE_URL is not configured.")
    if not settings.llm_is_configured:
        raise SystemExit("The DeepSeek-compatible LLM settings are incomplete.")
    assert settings.llm_base_url is not None
    assert settings.llm_model is not None

    policy = SQLSafetyPolicy(
        dialect=settings.sql_dialect,
        max_rows=settings.sql_max_rows,
        enabled=settings.sql_safety_enabled,
        allowed_schemas=frozenset(settings.sql_allowed_schemas),
    )
    database = PostgresAnalyticsDatabase(
        settings.database_url.get_secret_value(),
        policy=policy,
        statement_timeout_ms=settings.sql_statement_timeout_ms,
        max_estimated_cost=settings.sql_max_estimated_cost,
    )
    llm = OpenAICompatibleClient(
        base_url=settings.llm_base_url,
        api_key=resolve_llm_api_key(settings),
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        thinking_enabled=settings.llm_thinking_enabled,
    )
    run_repository = (
        PostgresAnalysisRunRepository(settings.metadata_database_url.get_secret_value())
        if settings.metadata_database_url is not None
        else None
    )
    try:
        generated_code_executor = (
            DockerSandboxExecutor(
                container_name=settings.sandbox_container_name,
                timeout_seconds=settings.sandbox_timeout_seconds,
                memory_mb=settings.sandbox_memory_mb,
                cpu_count=settings.sandbox_cpu_count,
            )
            if settings.enable_generated_python
            else None
        )
        agent = AnalysisAgent(
            database=database,
            llm=llm,
            policy=policy,
            model_name=settings.llm_model,
            schema_names=settings.sql_allowed_schemas,
            max_sql_retries=settings.sql_max_retries,
            generated_code_executor=generated_code_executor,
            run_repository=run_repository,
        )
        result = agent.analyze(AnalysisRequest(question=args.question))
        print(result.model_dump_json(indent=2))
    finally:
        llm.close()
        database.close()
        if run_repository is not None:
            run_repository.close()


if __name__ == "__main__":
    main()
