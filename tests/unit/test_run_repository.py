"""Tests for durable analysis-run state transitions."""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from datapilot.adapters.database.errors import UnsupportedDatabaseError
from datapilot.adapters.database.run_repository import PostgresAnalysisRunRepository
from datapilot.domain.common import ErrorInfo, RunStatus

RUN_ID = UUID("00000000-0000-0000-0000-000000000123")
STARTED_AT = datetime(2026, 8, 12, tzinfo=UTC)


def _repository(engine: MagicMock) -> PostgresAnalysisRunRepository:
    return PostgresAnalysisRunRepository(
        "postgresql+psycopg://metadata:hidden@example.test/analytics",
        engine=engine,
    )


def test_repository_requires_postgresql_and_valid_limit() -> None:
    with pytest.raises(UnsupportedDatabaseError):
        PostgresAnalysisRunRepository("sqlite:///runs.db")

    repository = _repository(MagicMock())
    with pytest.raises(ValueError, match="between 1 and 100"):
        repository.list_runs(limit=0)


def test_start_and_failure_transition_use_safe_parameters() -> None:
    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value
    connection.execute.return_value.rowcount = 1
    repository = _repository(engine)

    repository.start_run(
        run_id=RUN_ID,
        question="Analyze order status",
        session_id="session-1",
        model_name="deepseek-v4-flash",
        started_at=STARTED_AT,
    )
    repository.fail_run(
        run_id=RUN_ID,
        status=RunStatus.FAILED,
        completed_at=STARTED_AT,
        duration_ms=12.5,
        error=ErrorInfo(
            code="analysis_failed",
            message="The analysis failed unexpectedly.",
        ),
    )

    first_parameters = connection.execute.call_args_list[0].args[1]
    failure_parameters = connection.execute.call_args_list[1].args[1]
    assert first_parameters["status"] == "running"
    assert first_parameters["question"] == "Analyze order status"
    assert failure_parameters["status"] == "failed"
    assert "analysis_failed" in failure_parameters["error"]


def test_failure_transition_rejects_invalid_status_or_missing_row() -> None:
    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value
    repository = _repository(engine)

    with pytest.raises(ValueError, match="failed or rejected"):
        repository.fail_run(
            run_id=RUN_ID,
            status=RunStatus.SUCCEEDED,
            completed_at=STARTED_AT,
            duration_ms=1,
            error=ErrorInfo(code="x", message="x"),
        )

    connection.execute.return_value.rowcount = 0
    with pytest.raises(RuntimeError, match="transition"):
        repository.fail_run(
            run_id=RUN_ID,
            status=RunStatus.REJECTED,
            completed_at=STARTED_AT,
            duration_ms=1,
            error=ErrorInfo(code="rejected", message="Rejected safely."),
        )


def test_get_missing_run_and_list_summaries() -> None:
    engine = MagicMock()
    read_connection = engine.connect.return_value.__enter__.return_value
    repository = _repository(engine)
    read_connection.execute.return_value.mappings.return_value.one_or_none.return_value = None

    assert repository.get_run(RUN_ID) is None

    read_connection.execute.return_value.mappings.return_value = [
        {
            "run_id": RUN_ID,
            "status": "running",
            "question": "Analyze order status",
            "session_id": None,
            "model_name": "deepseek-v4-flash",
            "started_at": STARTED_AT,
            "completed_at": None,
            "duration_ms": None,
        }
    ]
    summaries = repository.list_runs(limit=10)

    assert summaries[0].run_id == RUN_ID
    assert summaries[0].status is RunStatus.RUNNING
    repository.close()
    engine.dispose.assert_called_once()


def test_connection_probe_uses_metadata_engine() -> None:
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar_one.return_value = 1

    assert _repository(engine).check_connection() is True
