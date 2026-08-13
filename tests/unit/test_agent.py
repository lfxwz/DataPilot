"""Tests for the end-to-end agent orchestration and deterministic evidence profile."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import ProgrammingError

from datapilot.adapters.database.errors import QueryPolicyError
from datapilot.domain.analysis import AnalysisRequest
from datapilot.domain.common import RunStatus
from datapilot.domain.llm import LLMUsage, StructuredCompletion
from datapilot.domain.query import QueryExecutionResult, QueryPlanSummary
from datapilot.domain.schema import ColumnMetadata, SchemaSnapshot, TableMetadata
from datapilot.domain.sql import SQLCandidate
from datapilot.policies.sql_safety import SQLSafetyPolicy
from datapilot.services.agent import AnalysisAgent
from datapilot.services.result_profiling import QueryResultProfiler


class FakeAgentLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
    ) -> StructuredCompletion:
        self.calls += 1
        if self.calls == 1:
            assert "planning component" in system_prompt
            assert max_tokens == 8000
            return completion(
                {
                    "objective": "Count orders by status",
                    "metrics": ["order_count"],
                    "dimensions": ["order_status"],
                    "steps": [
                        {
                            "id": "query_order_status",
                            "type": "sql",
                            "description": "Count orders grouped by status",
                            "depends_on": [],
                            "parameters": {},
                        }
                    ],
                }
            )
        if self.calls == 2:
            assert "generate PostgreSQL" in system_prompt
            assert max_tokens == 4000
            return completion(
                {
                    "sql": (
                        "SELECT order_status, COUNT(*) AS order_count "
                        "FROM olist.orders GROUP BY order_status ORDER BY order_count DESC"
                    ),
                    "purpose": "Count orders by status",
                }
            )
        assert "auditable data analysis" in system_prompt
        assert max_tokens == 4000
        assert "96478" in user_prompt
        assert "deterministic_analyses" in user_prompt
        return completion(
            {
                "summary": "Delivered orders dominate the observed result.",
                "findings": ["Delivered has 96,478 orders in the executed result."],
                "limitations": ["This is descriptive and does not establish causes."],
            }
        )


class FakeAgentDatabase:
    def inspect_schema(self, schema_names: tuple[str, ...]) -> SchemaSnapshot:
        assert schema_names == ("olist",)
        return SchemaSnapshot(
            database_name="analytics",
            tables=(
                TableMetadata(
                    schema_name="olist",
                    table_name="orders",
                    columns=(
                        ColumnMetadata(name="order_status", data_type="TEXT", nullable=False),
                    ),
                ),
            ),
        )

    def execute(self, candidate: SQLCandidate) -> QueryExecutionResult:
        assert candidate.sql.startswith("SELECT order_status")
        return QueryExecutionResult(
            query_hash="a" * 64,
            columns=("order_status", "order_count"),
            rows=(("delivered", 96_478), ("shipped", 1_107)),
            row_count=2,
            truncated=False,
            duration_ms=4.5,
            plan=QueryPlanSummary(node_type="Sort", estimated_cost=200.0, estimated_rows=8),
        )


def completion(data: dict[str, object]) -> StructuredCompletion:
    return StructuredCompletion(model="test-model", data=data, usage=LLMUsage())


def test_agent_runs_the_complete_auditable_pipeline() -> None:
    llm = FakeAgentLLM()
    agent = AnalysisAgent(
        database=FakeAgentDatabase(),  # type: ignore[arg-type]
        llm=llm,
        policy=SQLSafetyPolicy(allowed_schemas=frozenset({"olist"}), max_rows=100),
        model_name="test-model",
        schema_names=("olist",),
    )

    result = agent.analyze(AnalysisRequest(question="Count orders by status"))

    assert result.status == "succeeded"
    assert result.schema_tables == ("olist.orders",)
    assert result.sql_validation.accepted is True
    assert result.query_result.row_count == 2
    assert result.python_profile.columns[1].numeric is not None
    assert result.python_profile.columns[1].numeric.maximum == 96_478
    distribution = result.deterministic_analyses[0]
    assert distribution.method == "categorical_distribution"
    assert distribution.top_1_share == pytest.approx(96_478 / 97_585)  # type: ignore[union-attr]
    assert result.narrative.findings[0].startswith("Delivered")
    assert len(result.prompt_versions) == 3
    assert llm.calls == 3


def test_agent_repairs_database_error_and_retries_sql() -> None:
    class RepairLLM(FakeAgentLLM):
        def complete_json(
            self,
            *,
            system_prompt: str,
            user_prompt: str,
            max_tokens: int = 4000,
        ) -> StructuredCompletion:
            self.calls += 1
            if self.calls == 1:
                return completion(
                    {
                        "objective": "Count orders by status",
                        "metrics": ["order_count"],
                        "dimensions": ["order_status"],
                        "steps": [
                            {
                                "id": "query_order_status",
                                "type": "sql",
                                "description": "Count orders grouped by status",
                                "depends_on": [],
                                "parameters": {},
                            }
                        ],
                    }
                )
            if self.calls == 2:
                return completion(
                    {
                        "sql": "SELECT missing_column FROM olist.orders",
                        "purpose": "Count orders by status",
                    }
                )
            if self.calls == 3:
                assert "missing_column" in user_prompt
                assert "UndefinedColumn" in user_prompt
                assert "order_status" in user_prompt
                return completion(
                    {
                        "sql": (
                            "SELECT order_status, COUNT(*) AS order_count "
                            "FROM olist.orders GROUP BY order_status"
                        ),
                        "purpose": "Count orders by status after repair",
                    }
                )
            return completion(
                {
                    "summary": "Delivered orders dominate.",
                    "findings": ["Delivered has the highest order count."],
                    "limitations": ["This is descriptive."],
                }
            )

    class RepairDatabase(FakeAgentDatabase):
        def __init__(self) -> None:
            self.executed_sql: list[str] = []

        def execute(self, candidate: SQLCandidate) -> QueryExecutionResult:
            self.executed_sql.append(candidate.sql)
            if "missing_column" in candidate.sql:
                raise ProgrammingError(
                    candidate.sql,
                    {},
                    Exception('UndefinedColumn: column "missing_column" does not exist'),
                )
            return super().execute(candidate)

    database = RepairDatabase()
    llm = RepairLLM()
    agent = AnalysisAgent(
        database=database,  # type: ignore[arg-type]
        llm=llm,
        policy=SQLSafetyPolicy(enabled=False),
        model_name="test-model",
        schema_names=("olist",),
        max_sql_retries=2,
    )

    result = agent.analyze(AnalysisRequest(question="Count orders by status"))

    assert result.status is RunStatus.SUCCEEDED
    assert result.sql_retry_count == 1
    assert "missing_column" in database.executed_sql[0]
    assert result.sql_candidate.sql == database.executed_sql[1]
    assert "order_status" in result.sql_candidate.sql


def test_profiler_handles_nulls_decimals_text_and_empty_results() -> None:
    result = QueryExecutionResult(
        query_hash="b" * 64,
        columns=("category", "revenue"),
        rows=(("books", Decimal("10.50")), ("books", None), ("toys", Decimal("20.00"))),
        row_count=3,
        truncated=True,
        duration_ms=1,
        plan=QueryPlanSummary(node_type="Aggregate", estimated_cost=1, estimated_rows=3),
    )

    profile = QueryResultProfiler(sample_values=2).profile(result)

    assert profile.columns[0].distinct_count == 2
    assert profile.columns[0].sample_values == ("books", "toys")
    assert profile.columns[1].null_count == 1
    assert profile.columns[1].numeric is not None
    assert profile.columns[1].numeric.total == pytest.approx(30.5)

    empty = QueryExecutionResult(
        query_hash="c" * 64,
        columns=("order_id",),
        rows=(),
        row_count=0,
        truncated=False,
        duration_ms=1,
        plan=QueryPlanSummary(node_type="Result", estimated_cost=0, estimated_rows=0),
    )
    assert QueryResultProfiler().profile(empty).columns[0].numeric is None


def test_profiler_rejects_invalid_sample_limit() -> None:
    with pytest.raises(ValueError, match="positive"):
        QueryResultProfiler(sample_values=0)


def test_agent_persists_safe_rejection_without_swallowing_error() -> None:
    class FailingDatabase(FakeAgentDatabase):
        def inspect_schema(self, schema_names: tuple[str, ...]) -> SchemaSnapshot:
            raise QueryPolicyError("unsafe internal detail")

    repository = MagicMock()
    agent = AnalysisAgent(
        database=FailingDatabase(),  # type: ignore[arg-type]
        llm=FakeAgentLLM(),
        policy=SQLSafetyPolicy(allowed_schemas=frozenset({"olist"}), max_rows=100),
        model_name="test-model",
        schema_names=("olist",),
        run_repository=repository,
    )

    with pytest.raises(QueryPolicyError, match="unsafe internal detail"):
        agent.analyze(AnalysisRequest(question="Count orders by status", session_id="session-1"))

    repository.start_run.assert_called_once()
    failure = repository.fail_run.call_args.kwargs
    assert failure["status"] is RunStatus.REJECTED
    assert failure["error"].code == "sql_policy_rejected"
    assert failure["error"].message == "unsafe internal detail"
    repository.complete_run.assert_not_called()
