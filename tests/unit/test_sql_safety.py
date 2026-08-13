"""Security-focused tests for model-generated SQL."""

import pytest

from datapilot.domain.sql import SQLCandidate, SQLRiskLevel
from datapilot.policies.sql_safety import SQLSafetyPolicy


def candidate(sql: str) -> SQLCandidate:
    return SQLCandidate(sql=sql, dialect="postgres", purpose="Test analytical query")


def issue_codes(sql: str, policy: SQLSafetyPolicy | None = None) -> set[str]:
    result = (policy or SQLSafetyPolicy()).validate(candidate(sql))
    return {issue.code for issue in result.issues}


def test_select_is_accepted_and_gets_limit() -> None:
    result = SQLSafetyPolicy(max_rows=50).validate(candidate("SELECT order_id FROM olist.orders"))

    assert result.accepted is True
    assert result.risk_level is SQLRiskLevel.LOW
    assert result.referenced_tables == ("olist.orders",)
    assert result.normalized_sql is not None
    assert "LIMIT 50" in result.normalized_sql


def test_excessive_existing_limit_is_capped() -> None:
    result = SQLSafetyPolicy(max_rows=50).validate(candidate("SELECT * FROM orders LIMIT 500"))

    assert result.accepted is True
    assert result.normalized_sql is not None
    assert "LIMIT 50" in result.normalized_sql
    assert "LIMIT 500" not in result.normalized_sql


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "UPDATE orders SET status = 'cancelled'",
        "INSERT INTO orders (order_id) VALUES (1)",
        "DROP TABLE orders",
        "SELECT * FROM orders FOR UPDATE",
    ],
)
def test_write_or_locking_statement_is_rejected(sql: str) -> None:
    result = SQLSafetyPolicy().validate(candidate(sql))

    assert result.accepted is False
    assert result.risk_level is SQLRiskLevel.HIGH


def test_multiple_statements_are_rejected() -> None:
    assert issue_codes("SELECT 1; SELECT 2") == {"multiple_statements"}


def test_blocked_postgres_function_is_rejected() -> None:
    assert "blocked_function" in issue_codes("SELECT pg_read_file('/etc/passwd')")


def test_system_schema_is_rejected() -> None:
    assert "blocked_schema" in issue_codes("SELECT * FROM pg_catalog.pg_roles")


def test_disabled_policy_accepts_sql_without_validation_or_normalization() -> None:
    sql = "SELECT * FROM pg_catalog.pg_roles; SELECT pg_read_file('/etc/passwd')"

    result = SQLSafetyPolicy(enabled=False, max_rows=1).validate(candidate(sql))

    assert result.accepted is True
    assert result.risk_level is SQLRiskLevel.HIGH
    assert result.normalized_sql == sql
    assert result.issues == ()


def test_table_allowlist_is_enforced() -> None:
    policy = SQLSafetyPolicy(allowed_tables=frozenset({"olist.orders"}))

    assert policy.validate(candidate("SELECT * FROM olist.orders")).accepted is True
    assert "table_not_allowed" in issue_codes("SELECT * FROM olist.customers", policy)


def test_cte_alias_is_not_treated_as_physical_table() -> None:
    result = SQLSafetyPolicy().validate(
        candidate(
            "WITH revenue AS (SELECT order_id, price FROM olist.order_items) "
            "SELECT order_id, SUM(price) FROM revenue GROUP BY order_id"
        )
    )

    assert result.accepted is True
    assert result.referenced_tables == ("olist.order_items",)


def test_window_query_is_classified_as_medium_complexity() -> None:
    result = SQLSafetyPolicy().validate(
        candidate("SELECT order_id, ROW_NUMBER() OVER (ORDER BY order_id) AS rn FROM orders")
    )

    assert result.accepted is True
    assert result.risk_level is SQLRiskLevel.MEDIUM
