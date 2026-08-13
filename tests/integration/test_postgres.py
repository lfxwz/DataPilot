"""PostgreSQL integration tests for the database-level safety boundary."""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from datapilot.adapters.database import PostgresAnalyticsDatabase
from datapilot.adapters.database.errors import QueryPolicyError
from datapilot.domain.sql import SQLCandidate
from datapilot.policies.sql_safety import SQLSafetyPolicy

pytestmark = pytest.mark.postgres


@pytest.fixture
def database_url() -> str:
    url = os.getenv("DATAPILOT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("DATAPILOT_TEST_DATABASE_URL is not configured")
    return url


@pytest.fixture
def analytics_database(database_url: str) -> PostgresAnalyticsDatabase:
    database = PostgresAnalyticsDatabase(
        database_url,
        policy=SQLSafetyPolicy(
            dialect="postgres",
            max_rows=10,
            allowed_schemas=frozenset({"olist"}),
        ),
        statement_timeout_ms=5_000,
        max_estimated_cost=10_000,
    )
    yield database
    database.close()


def test_schema_snapshot_contains_columns_and_relationships(
    analytics_database: PostgresAnalyticsDatabase,
) -> None:
    snapshot = analytics_database.inspect_schema(["olist"])

    tables = {table.qualified_name: table for table in snapshot.tables}
    assert "olist.orders" in tables
    assert "olist.order_items" in tables
    assert "order_id" in {column.name for column in tables["olist.orders"].columns}
    relationships = tables["olist.order_items"].foreign_keys
    assert any(foreign_key.referred_table == "orders" for foreign_key in relationships)


def test_validated_query_executes_with_plan_and_limit(
    analytics_database: PostgresAnalyticsDatabase,
) -> None:
    result = analytics_database.execute(
        SQLCandidate(
            sql=(
                "SELECT order_status, COUNT(*) AS order_count "
                "FROM olist.orders GROUP BY order_status ORDER BY order_status"
            ),
            purpose="Count public Olist orders by lifecycle status",
        )
    )

    assert result.columns == ("order_status", "order_count")
    assert result.row_count > 0
    assert result.plan.estimated_cost >= 0
    assert result.query_hash


def test_policy_rejects_write_before_database_execution(
    analytics_database: PostgresAnalyticsDatabase,
) -> None:
    with pytest.raises(QueryPolicyError):
        analytics_database.execute(
            SQLCandidate(
                sql="DELETE FROM olist.orders",
                purpose="Verify deterministic write rejection",
            )
        )


def test_database_role_cannot_write_even_without_policy(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection, pytest.raises(DBAPIError):
            connection.execute(
                text(
                    "INSERT INTO olist.product_category_translation "
                    "(product_category_name, product_category_name_english) "
                    "VALUES ('forbidden', 'forbidden')"
                )
            )
    finally:
        engine.dispose()
