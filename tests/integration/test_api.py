"""HTTP contract tests for the initial API surface."""

import pytest
from fastapi.testclient import TestClient

from datapilot.api import create_app
from datapilot.api.dependencies import get_analysis_agent, get_analysis_run_repository
from datapilot.config import Settings


def test_liveness_and_request_correlation() -> None:
    app = create_app(Settings(_env_file=None, environment="test"))

    with TestClient(app) as client:
        response = client.get("/api/v1/health/live", headers={"X-Request-ID": "test-request"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request"
    assert response.json()["status"] == "ok"


def test_readiness_is_unavailable_without_database_configuration() -> None:
    app = create_app(Settings(_env_file=None, environment="test"))

    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["database_configured"] is False


def test_sql_validation_endpoint_never_executes_sql() -> None:
    app = create_app(Settings(_env_file=None, environment="test", sql_max_rows=20))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/sql/validate",
            json={
                "sql": "SELECT order_id FROM olist.orders",
                "dialect": "postgres",
                "purpose": "List orders for analysis",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert "LIMIT 20" in body["normalized_sql"]


def test_deterministic_analysis_endpoint() -> None:
    app = create_app(Settings(_env_file=None, environment="test"))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/analysis/run",
            json={
                "analysis_type": "two_proportion_test",
                "group_a_label": "campaign_a",
                "group_a_successes": 120,
                "group_a_trials": 1000,
                "group_b_label": "campaign_b",
                "group_b_successes": 90,
                "group_b_trials": 1000,
                "confidence_level": 0.95,
            },
        )

    assert response.status_code == 200
    assert response.json()["p_value"] == pytest.approx(0.0287, abs=0.0001)


def test_agent_endpoint_is_disabled_by_default() -> None:
    app = create_app(Settings(_env_file=None, environment="test"))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/agent/analyze",
            json={"question": "Count orders by status"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "The analysis agent API is disabled."


def test_enabled_agent_endpoint_returns_auditable_envelope() -> None:
    app = create_app(Settings(_env_file=None, environment="test", enable_agent_api=True))

    class FakeAgent:
        def analyze(self, request: object) -> dict[str, object]:
            return {
                "run_id": "00000000-0000-0000-0000-000000000001",
                "status": "succeeded",
                "question": "Count orders by status",
                "started_at": "2026-08-12T00:00:00Z",
                "completed_at": "2026-08-12T00:00:01Z",
                "duration_ms": 1000,
                "model_name": "test-model",
                "prompt_versions": ["planner-v1", "sql-v1", "synthesis-v1"],
                "schema_tables": ["olist.orders"],
                "plan": {
                    "objective": "Count orders by status",
                    "metrics": ["order_count"],
                    "dimensions": ["order_status"],
                    "steps": [
                        {
                            "id": "query_orders",
                            "type": "sql",
                            "description": "Count orders by status",
                            "depends_on": [],
                            "parameters": {},
                        }
                    ],
                },
                "sql_candidate": {
                    "sql": "SELECT order_status, COUNT(*) FROM olist.orders GROUP BY 1",
                    "dialect": "postgres",
                    "purpose": "Count orders by status",
                },
                "sql_validation": {
                    "accepted": True,
                    "risk_level": "low",
                    "normalized_sql": (
                        "SELECT order_status, COUNT(*) FROM olist.orders GROUP BY 1 LIMIT 100"
                    ),
                    "referenced_tables": ["olist.orders"],
                    "issues": [],
                },
                "query_result": {
                    "query_hash": "a" * 64,
                    "columns": ["order_status", "order_count"],
                    "rows": [["delivered", 96478]],
                    "row_count": 1,
                    "truncated": False,
                    "duration_ms": 5,
                    "plan": {"node_type": "Aggregate", "estimated_cost": 10, "estimated_rows": 1},
                },
                "python_profile": {
                    "row_count": 1,
                    "truncated": False,
                    "columns": [
                        {
                            "name": "order_status",
                            "non_null_count": 1,
                            "null_count": 0,
                            "distinct_count": 1,
                            "numeric": None,
                            "sample_values": ["delivered"],
                        }
                    ],
                },
                "deterministic_analyses": [
                    {
                        "method": "categorical_distribution",
                        "dimension_column": "order_status",
                        "metric_column": "order_count",
                        "total": 96478,
                        "top_1_share": 1,
                        "top_3_share": 1,
                        "points": [
                            {
                                "label": "delivered",
                                "value": 96478,
                                "rank": 1,
                                "share": 1,
                                "cumulative_share": 1,
                            }
                        ],
                        "limitations": ["Descriptive analysis only."],
                    }
                ],
                "narrative": {
                    "summary": "Delivered dominates.",
                    "findings": ["Delivered has 96,478 orders."],
                    "limitations": ["Descriptive result only."],
                },
            }

    app.dependency_overrides[get_analysis_agent] = lambda: FakeAgent()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/agent/analyze",
            json={"question": "Count orders by status"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    assert response.json()["sql_validation"]["accepted"] is True


def test_run_history_endpoints_list_get_and_404() -> None:
    app = create_app(Settings(_env_file=None, environment="test", enable_agent_api=True))

    class FakeRepository:
        def list_runs(self, *, limit: int) -> tuple[dict[str, object], ...]:
            assert limit == 5
            return (
                {
                    "run_id": "00000000-0000-0000-0000-000000000002",
                    "status": "rejected",
                    "question": "Run an unsafe query",
                    "session_id": "session-1",
                    "model_name": "test-model",
                    "started_at": "2026-08-12T00:00:00Z",
                    "completed_at": "2026-08-12T00:00:01Z",
                    "duration_ms": 1000,
                },
            )

        def get_run(self, run_id: object) -> dict[str, object] | None:
            if str(run_id).endswith("0002"):
                return {
                    **self.list_runs(limit=5)[0],
                    "result": None,
                    "error": {
                        "code": "sql_policy_rejected",
                        "message": "SQL was rejected by policy.",
                        "retryable": False,
                        "details": {},
                    },
                }
            return None

    app.dependency_overrides[get_analysis_run_repository] = lambda: FakeRepository()
    with TestClient(app) as client:
        listed = client.get("/api/v1/agent/runs?limit=5")
        found = client.get("/api/v1/agent/runs/00000000-0000-0000-0000-000000000002")
        missing = client.get("/api/v1/agent/runs/00000000-0000-0000-0000-000000000003")

    assert listed.status_code == 200
    assert listed.json()["items"][0]["status"] == "rejected"
    assert found.status_code == 200
    assert found.json()["error"]["code"] == "sql_policy_rejected"
    assert missing.status_code == 404


def test_report_download_rejects_failed_run() -> None:
    app = create_app(Settings(_env_file=None, environment="test", enable_agent_api=True))

    class FailedRunRepository:
        def get_run(self, run_id: object) -> dict[str, object]:
            return {
                "run_id": str(run_id),
                "status": "failed",
                "question": "Failed analysis",
                "session_id": None,
                "model_name": "test-model",
                "started_at": "2026-08-12T00:00:00Z",
                "completed_at": "2026-08-12T00:00:01Z",
                "duration_ms": 1000,
                "result": None,
                "error": {
                    "code": "analysis_failed",
                    "message": "The analysis failed unexpectedly.",
                    "retryable": False,
                    "details": {},
                },
            }

    app.dependency_overrides[get_analysis_run_repository] = lambda: FailedRunRepository()
    with TestClient(app) as client:
        response = client.get("/api/v1/agent/runs/00000000-0000-0000-0000-000000000004/report")

    assert response.status_code == 409
