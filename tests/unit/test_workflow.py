"""Tests for the first executable LangGraph workflow slice."""

from datapilot.domain.common import RunStatus
from datapilot.domain.sql import SQLCandidate
from datapilot.policies.sql_safety import SQLSafetyPolicy
from datapilot.workflows import build_sql_validation_graph


def test_graph_marks_safe_query_as_succeeded() -> None:
    graph = build_sql_validation_graph(SQLSafetyPolicy(max_rows=25))

    result = graph.invoke(
        {
            "sql_candidate": SQLCandidate(
                sql="SELECT order_id FROM orders",
                purpose="List orders for analysis",
            )
        }
    )

    assert result["status"] is RunStatus.SUCCEEDED
    assert result["sql_validation"].accepted is True
    assert result["error"] is None


def test_graph_marks_write_query_as_rejected() -> None:
    graph = build_sql_validation_graph(SQLSafetyPolicy())

    result = graph.invoke(
        {
            "sql_candidate": SQLCandidate(
                sql="DELETE FROM orders",
                purpose="Unsafe query used by a policy test",
            )
        }
    )

    assert result["status"] is RunStatus.REJECTED
    assert result["sql_validation"].accepted is False
    assert result["error"].code == "sql_policy_rejected"
