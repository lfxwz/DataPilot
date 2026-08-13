"""Tests for typed SQL generation before deterministic policy enforcement."""

from datapilot.domain.analysis import (
    AnalysisPlan,
    AnalysisRequest,
    AnalysisStep,
    StepType,
)
from datapilot.domain.llm import LLMUsage, StructuredCompletion
from datapilot.domain.schema import ColumnMetadata, SchemaSnapshot, TableMetadata
from datapilot.domain.sql import SQLCandidate
from datapilot.policies.sql_safety import SQLSafetyPolicy
from datapilot.services.sql_generation import SQLGenerator


class FakeSQLLLM:
    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
    ) -> StructuredCompletion:
        assert "exactly one PostgreSQL statement" in system_prompt
        assert "olist.order_items" in user_prompt
        assert "olist.orders" in user_prompt
        return StructuredCompletion(
            model="test-model",
            data={
                "sql": (
                    "SELECT o.order_status, SUM(i.price) AS item_revenue "
                    "FROM olist.orders AS o "
                    "JOIN olist.order_items AS i ON i.order_id = o.order_id "
                    "GROUP BY o.order_status"
                ),
                "purpose": "Calculate Olist item revenue by order status",
            },
            usage=LLMUsage(),
        )


def test_generated_candidate_must_still_pass_sql_policy() -> None:
    schema = SchemaSnapshot(
        database_name="analytics",
        tables=(
            TableMetadata(
                schema_name="olist",
                table_name="orders",
                columns=(
                    ColumnMetadata(
                        name="order_id",
                        data_type="TEXT",
                        nullable=False,
                    ),
                    ColumnMetadata(
                        name="order_status",
                        data_type="TEXT",
                        nullable=False,
                    ),
                ),
            ),
            TableMetadata(
                schema_name="olist",
                table_name="order_items",
                columns=(
                    ColumnMetadata(
                        name="order_id",
                        data_type="TEXT",
                        nullable=False,
                    ),
                    ColumnMetadata(
                        name="price",
                        data_type="NUMERIC(14, 2)",
                        nullable=True,
                    ),
                ),
            ),
        ),
    )
    plan = AnalysisPlan(
        objective="Analyze item revenue by order status",
        metrics=("item_revenue",),
        dimensions=("order_status",),
        steps=(
            AnalysisStep(
                id="query_revenue",
                type=StepType.SQL,
                description="Aggregate Olist item revenue by order status",
            ),
        ),
    )

    candidate = SQLGenerator(FakeSQLLLM()).generate(
        AnalysisRequest(question="Which order status has the highest item revenue?"),
        plan,
        schema,
    )
    validation = SQLSafetyPolicy(
        allowed_schemas=frozenset({"olist"}),
        max_rows=100,
    ).validate(candidate)

    assert validation.accepted is True
    assert validation.referenced_tables == ("olist.order_items", "olist.orders")
    assert validation.normalized_sql is not None
    assert "LIMIT 100" in validation.normalized_sql


class FakeRepairLLM:
    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
    ) -> StructuredCompletion:
        assert "repair context" in system_prompt
        assert "missing_column" in user_prompt
        assert "SELECT missing_column FROM olist.orders" in user_prompt
        assert '"name": "order_status"' in user_prompt
        return StructuredCompletion(
            model="test-model",
            data={
                "sql": "SELECT order_status FROM olist.orders",
                "purpose": "Repair the failed order query",
            },
            usage=LLMUsage(),
        )


def test_repair_uses_failed_sql_database_error_and_grounded_schema() -> None:
    schema = SchemaSnapshot(
        database_name="analytics",
        tables=(
            TableMetadata(
                schema_name="olist",
                table_name="orders",
                columns=(ColumnMetadata(name="order_status", data_type="TEXT", nullable=False),),
            ),
        ),
    )
    plan = AnalysisPlan(
        objective="List order statuses",
        metrics=(),
        dimensions=("order_status",),
        steps=(
            AnalysisStep(
                id="query_status",
                type=StepType.SQL,
                description="Read order status values",
            ),
        ),
    )

    repaired = SQLGenerator(FakeRepairLLM()).repair(
        AnalysisRequest(question="What order data exists?"),
        plan,
        schema,
        failed_candidate=SQLCandidate(
            sql="SELECT missing_column FROM olist.orders",
            purpose="Failed order query",
        ),
        database_error='UndefinedColumn: column "missing_column" does not exist',
        attempt=1,
    )

    assert repaired.sql == "SELECT order_status FROM olist.orders"
