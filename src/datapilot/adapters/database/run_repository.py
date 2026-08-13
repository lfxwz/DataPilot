"""PostgreSQL persistence for synchronous analysis-run audit records."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from datapilot.adapters.database.errors import UnsupportedDatabaseError
from datapilot.domain.agent import AgentAnalysisResult
from datapilot.domain.common import ErrorInfo, RunStatus
from datapilot.domain.run_history import AnalysisRunRecord, AnalysisRunSummary


class PostgresAnalysisRunRepository:
    """Store run state through a role limited to one metadata table."""

    def __init__(self, database_url: str, *, engine: Engine | None = None) -> None:
        url = make_url(database_url)
        if url.get_backend_name() != "postgresql":
            raise UnsupportedDatabaseError("PostgresAnalysisRunRepository requires PostgreSQL.")
        self._engine = engine or create_engine(
            url,
            pool_pre_ping=True,
            pool_size=3,
            max_overflow=2,
            pool_timeout=10,
            hide_parameters=True,
        )

    def close(self) -> None:
        self._engine.dispose()

    def check_connection(self) -> bool:
        with self._engine.connect() as connection:
            value = connection.execute(text("SELECT 1")).scalar_one()
            return bool(value == 1)

    def start_run(
        self,
        *,
        run_id: UUID,
        question: str,
        session_id: str | None,
        model_name: str,
        started_at: datetime,
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO datapilot_meta.analysis_runs (
                        run_id, status, question, session_id, model_name, started_at
                    ) VALUES (
                        :run_id, :status, :question, :session_id, :model_name, :started_at
                    )
                    """
                ),
                {
                    "run_id": run_id,
                    "status": RunStatus.RUNNING.value,
                    "question": question,
                    "session_id": session_id,
                    "model_name": model_name,
                    "started_at": started_at,
                },
            )

    def complete_run(self, result: AgentAnalysisResult) -> None:
        payload = result.model_dump(mode="json")
        with self._engine.begin() as connection:
            updated = connection.execute(
                text(
                    """
                    UPDATE datapilot_meta.analysis_runs
                    SET status = :status,
                        completed_at = :completed_at,
                        duration_ms = :duration_ms,
                        result = CAST(:result AS jsonb),
                        error = NULL
                    WHERE run_id = :run_id AND status = :expected_status
                    """
                ),
                {
                    "run_id": result.run_id,
                    "status": RunStatus.SUCCEEDED.value,
                    "expected_status": RunStatus.RUNNING.value,
                    "completed_at": result.completed_at,
                    "duration_ms": result.duration_ms,
                    "result": json.dumps(payload, ensure_ascii=False, allow_nan=False),
                },
            )
            if updated.rowcount != 1:
                raise RuntimeError("analysis run did not transition from running to succeeded")

    def fail_run(
        self,
        *,
        run_id: UUID,
        status: RunStatus,
        completed_at: datetime,
        duration_ms: float,
        error: ErrorInfo,
    ) -> None:
        if status not in {RunStatus.FAILED, RunStatus.REJECTED}:
            raise ValueError("terminal error status must be failed or rejected")
        with self._engine.begin() as connection:
            updated = connection.execute(
                text(
                    """
                    UPDATE datapilot_meta.analysis_runs
                    SET status = :status,
                        completed_at = :completed_at,
                        duration_ms = :duration_ms,
                        result = NULL,
                        error = CAST(:error AS jsonb)
                    WHERE run_id = :run_id AND status = :expected_status
                    """
                ),
                {
                    "run_id": run_id,
                    "status": status.value,
                    "expected_status": RunStatus.RUNNING.value,
                    "completed_at": completed_at,
                    "duration_ms": duration_ms,
                    "error": error.model_dump_json(),
                },
            )
            if updated.rowcount != 1:
                raise RuntimeError("analysis run did not transition to an error state")

    def get_run(self, run_id: UUID) -> AnalysisRunRecord | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT run_id, status, question, session_id, model_name,
                           started_at, completed_at, duration_ms, result, error
                    FROM datapilot_meta.analysis_runs
                    WHERE run_id = :run_id
                    """
                    ),
                    {"run_id": run_id},
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else self._record_from_mapping(dict(row))

    def list_runs(self, *, limit: int = 20) -> tuple[AnalysisRunSummary, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT run_id, status, question, session_id, model_name,
                           started_at, completed_at, duration_ms
                    FROM datapilot_meta.analysis_runs
                    ORDER BY started_at DESC, run_id DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).mappings()
            return tuple(AnalysisRunSummary.model_validate(dict(row)) for row in rows)

    @staticmethod
    def _record_from_mapping(row: dict[str, Any]) -> AnalysisRunRecord:
        result = row.get("result")
        error = row.get("error")
        row["result"] = None if result is None else AgentAnalysisResult.model_validate(result)
        row["error"] = None if error is None else ErrorInfo.model_validate(error)
        return AnalysisRunRecord.model_validate(row)
