"""Isolated tests for PostgreSQL safety behavior without a running server."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from datapilot.adapters.database.errors import (
    QueryBudgetExceededError,
    QueryPolicyError,
    ReadOnlyBoundaryError,
    UnsupportedDatabaseError,
)
from datapilot.adapters.database.postgres import PostgresAnalyticsDatabase
from datapilot.domain.sql import SQLCandidate
from datapilot.policies.sql_safety import SQLSafetyPolicy


def make_adapter(engine: MagicMock, *, max_cost: float = 100.0) -> PostgresAnalyticsDatabase:
    return PostgresAnalyticsDatabase(
        "postgresql+psycopg://readonly:hidden@example.test/analytics",
        policy=SQLSafetyPolicy(max_rows=2, allowed_schemas=frozenset({"olist"})),
        statement_timeout_ms=1_000,
        max_estimated_cost=max_cost,
        engine=engine,
    )


def connection_context(engine: MagicMock) -> MagicMock:
    connection = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    return connection


def test_constructor_rejects_unsupported_or_unsafe_configuration() -> None:
    with pytest.raises(UnsupportedDatabaseError):
        PostgresAnalyticsDatabase(
            "sqlite:///local.db",
            policy=SQLSafetyPolicy(),
        )
    with pytest.raises(ValueError, match="at least 100"):
        PostgresAnalyticsDatabase(
            "postgresql://example.test/analytics",
            policy=SQLSafetyPolicy(),
            statement_timeout_ms=99,
        )
    with pytest.raises(ValueError, match="positive"):
        PostgresAnalyticsDatabase(
            "postgresql://example.test/analytics",
            policy=SQLSafetyPolicy(),
            max_estimated_cost=0,
        )


def test_connection_probe_enforces_read_only_and_rolls_back() -> None:
    engine = MagicMock()
    connection = connection_context(engine)
    connection.execute.return_value.scalar_one.side_effect = [True, 1]
    adapter = make_adapter(engine)

    assert adapter.check_connection() is True
    connection.begin.return_value.rollback.assert_called_once()
    adapter.close()
    engine.dispose.assert_called_once()


def test_read_only_boundary_rejects_unconfirmed_transaction() -> None:
    engine = MagicMock()
    connection = connection_context(engine)
    connection.execute.return_value.scalar_one.return_value = False
    adapter = make_adapter(engine)

    with pytest.raises(ReadOnlyBoundaryError):
        adapter.check_connection()
    connection.begin.return_value.rollback.assert_called_once()


def test_schema_inspection_returns_grounded_keys_and_comments() -> None:
    engine = MagicMock()
    connection = connection_context(engine)
    inspector = MagicMock()
    inspector.get_table_names.return_value = ["orders"]
    inspector.get_columns.return_value = [
        {"name": "order_id", "type": "TEXT", "nullable": False, "default": None}
    ]
    inspector.get_pk_constraint.return_value = {"constrained_columns": ["order_id"]}
    inspector.get_foreign_keys.return_value = []
    inspector.get_table_comment.return_value = {"text": "Public Olist orders"}
    connection.execute.return_value = [
        SimpleNamespace(column_name="order_id", comment="Anonymized order identifier")
    ]
    adapter = make_adapter(engine)

    with patch("datapilot.adapters.database.postgres.inspect", return_value=inspector):
        snapshot = adapter.inspect_schema(["olist", "olist"])

    assert snapshot.database_name == "analytics"
    assert len(snapshot.tables) == 1
    assert snapshot.tables[0].qualified_name == "olist.orders"
    assert snapshot.tables[0].primary_key == ("order_id",)
    assert snapshot.tables[0].columns[0].comment == "Anonymized order identifier"
    with pytest.raises(ValueError, match="at least one schema"):
        adapter.inspect_schema([])


def test_execution_is_policy_checked_budgeted_bounded_and_rolled_back() -> None:
    engine = MagicMock()
    connection = connection_context(engine)
    read_only_result = MagicMock()
    read_only_result.scalar_one.return_value = True
    explain_result = MagicMock()
    explain_result.scalar_one.return_value = [
        {"Plan": {"Node Type": "Seq Scan", "Total Cost": 12.5, "Plan Rows": 3}}
    ]
    query_result = MagicMock()
    query_result.keys.return_value = ["order_id"]
    query_result.fetchmany.return_value = [("one",), ("two",), ("three",)]
    connection.execute.side_effect = [
        MagicMock(),
        MagicMock(),
        read_only_result,
        explain_result,
        query_result,
    ]
    adapter = make_adapter(engine)

    result = adapter.execute(
        SQLCandidate(sql="SELECT order_id FROM olist.orders", purpose="Bounded order sample")
    )

    assert result.columns == ("order_id",)
    assert result.rows == (("one",), ("two",))
    assert result.truncated is True
    assert result.plan.estimated_cost == 12.5
    connection.begin.return_value.rollback.assert_called_once()


def test_execution_rejects_policy_failure_before_connecting() -> None:
    engine = MagicMock()
    adapter = make_adapter(engine)

    with pytest.raises(QueryPolicyError):
        adapter.execute(SQLCandidate(sql="DELETE FROM olist.orders", purpose="Forbidden write"))

    engine.connect.assert_not_called()


def test_execution_rejects_excessive_explain_cost_and_rolls_back() -> None:
    engine = MagicMock()
    connection = connection_context(engine)
    read_only_result = MagicMock()
    read_only_result.scalar_one.return_value = True
    explain_result = MagicMock()
    explain_result.scalar_one.return_value = [
        {"Plan": {"Node Type": "Seq Scan", "Total Cost": 999.0, "Plan Rows": 100_000}}
    ]
    connection.execute.side_effect = [MagicMock(), MagicMock(), read_only_result, explain_result]
    adapter = make_adapter(engine, max_cost=10.0)

    with pytest.raises(QueryBudgetExceededError):
        adapter.execute(SQLCandidate(sql="SELECT * FROM olist.orders", purpose="Too expensive"))

    connection.begin.return_value.rollback.assert_called_once()


def test_unrestricted_execution_skips_policy_boundaries_and_returns_all_rows() -> None:
    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value
    query_result = MagicMock()
    query_result.returns_rows = True
    query_result.keys.return_value = ["order_id"]
    query_result.fetchall.return_value = [("one",), ("two",), ("three",)]
    connection.execute.return_value = query_result
    adapter = PostgresAnalyticsDatabase(
        "postgresql+psycopg://unrestricted:hidden@example.test/analytics",
        policy=SQLSafetyPolicy(enabled=False, max_rows=1),
        engine=engine,
    )

    result = adapter.execute(
        SQLCandidate(sql="SELECT order_id FROM olist.orders", purpose="Unrestricted sample")
    )

    assert result.rows == (("one",), ("two",), ("three",))
    assert result.truncated is False
    assert result.plan.node_type == "Unrestricted execution"
    engine.connect.assert_not_called()
    connection.execute.assert_called_once()
