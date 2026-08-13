"""Shared domain primitives."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base model that rejects silently ignored or mutated input."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(UTC)


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"


class ErrorInfo(StrictModel):
    """Safe, structured error information stored in workflow state."""

    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2000)
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class RunContext(StrictModel):
    """Stable identifiers and version metadata for one analysis run."""

    run_id: UUID = Field(default_factory=uuid4)
    request_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=utc_now)
    prompt_version: str = "unconfigured"
    model_name: str = "unconfigured"
