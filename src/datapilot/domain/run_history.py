"""Persistent audit contracts for synchronous analysis runs."""

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from datapilot.domain.agent import AgentAnalysisResult
from datapilot.domain.common import ErrorInfo, RunStatus, StrictModel


class AnalysisRunSummary(StrictModel):
    run_id: UUID
    status: RunStatus
    question: str = Field(min_length=3, max_length=4000)
    session_id: str | None = Field(default=None, max_length=200)
    model_name: str = Field(min_length=1, max_length=255)
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0)


class AnalysisRunRecord(AnalysisRunSummary):
    """One durable run with either a result or a safe error envelope."""

    result: AgentAnalysisResult | None = None
    error: ErrorInfo | None = None

    @model_validator(mode="after")
    def validate_terminal_payload(self) -> "AnalysisRunRecord":
        if self.status is RunStatus.SUCCEEDED and self.result is None:
            raise ValueError("a succeeded run requires a result")
        if self.status in {RunStatus.FAILED, RunStatus.REJECTED} and self.error is None:
            raise ValueError("a failed or rejected run requires an error")
        if self.result is not None and self.error is not None:
            raise ValueError("a run cannot contain both result and error")
        if self.result is not None:
            if self.result.run_id != self.run_id:
                raise ValueError("stored result run_id must match the audit record")
            if self.result.status is not self.status:
                raise ValueError("stored result status must match the audit record")
            if self.result.started_at != self.started_at:
                raise ValueError("stored result started_at must match the audit record")
            if self.result.completed_at != self.completed_at:
                raise ValueError("stored result completed_at must match the audit record")
        return self


class AnalysisRunPage(StrictModel):
    items: tuple[AnalysisRunSummary, ...]
    limit: int = Field(ge=1, le=100)
