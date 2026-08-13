"""SQL generation, policy, and execution contracts."""

from enum import StrEnum

from pydantic import Field

from datapilot.domain.common import StrictModel


class SQLRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SQLCandidate(StrictModel):
    """SQL produced for a particular analysis objective."""

    sql: str = Field(min_length=1, max_length=100_000)
    dialect: str = Field(default="postgres", min_length=1, max_length=50)
    purpose: str = Field(min_length=3, max_length=1000)


class SQLValidationIssue(StrictModel):
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)


class SQLValidationResult(StrictModel):
    """Deterministic output of the SQL safety gateway."""

    accepted: bool
    risk_level: SQLRiskLevel
    normalized_sql: str | None = None
    referenced_tables: tuple[str, ...] = ()
    issues: tuple[SQLValidationIssue, ...] = ()
