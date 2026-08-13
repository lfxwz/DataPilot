"""Typed contracts for one auditable end-to-end analysis-agent run."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from datapilot.domain.analysis import AnalysisPlan
from datapilot.domain.common import RunStatus, StrictModel
from datapilot.domain.generated_python import GeneratedPythonAnalysis
from datapilot.domain.query import QueryExecutionResult
from datapilot.domain.sql import SQLCandidate, SQLValidationResult


class NumericSummary(StrictModel):
    minimum: float
    maximum: float
    mean: float
    total: float


class ColumnProfile(StrictModel):
    name: str
    non_null_count: int = Field(ge=0)
    null_count: int = Field(ge=0)
    distinct_count: int = Field(ge=0)
    numeric: NumericSummary | None = None
    sample_values: tuple[str, ...] = ()


class QueryResultProfile(StrictModel):
    """Deterministic Python profile of the bounded SQL result."""

    row_count: int = Field(ge=0)
    truncated: bool
    columns: tuple[ColumnProfile, ...]


class DeterministicAnalysisMethod(StrEnum):
    CATEGORICAL_DISTRIBUTION = "categorical_distribution"
    TIME_SERIES_CHANGE = "time_series_change"


class DistributionPoint(StrictModel):
    label: str
    value: float
    rank: int = Field(ge=1)
    share: float | None = Field(default=None, ge=0, le=1)
    cumulative_share: float | None = Field(default=None, ge=0, le=1)


class DistributionAnalysis(StrictModel):
    method: DeterministicAnalysisMethod = DeterministicAnalysisMethod.CATEGORICAL_DISTRIBUTION
    dimension_column: str
    metric_column: str
    total: float
    top_1_share: float | None = Field(default=None, ge=0, le=1)
    top_3_share: float | None = Field(default=None, ge=0, le=1)
    points: tuple[DistributionPoint, ...]
    limitations: tuple[str, ...] = ()


class TimeSeriesPoint(StrictModel):
    period: str
    value: float
    comparison_valid: bool = False
    suspected_partial_period: bool = False
    absolute_change: float | None = None
    percent_change: float | None = None
    change_z_score: float | None = None
    is_anomaly: bool = False


class TimeSeriesAnalysis(StrictModel):
    method: DeterministicAnalysisMethod = DeterministicAnalysisMethod.TIME_SERIES_CHANGE
    dimension_column: str
    metric_column: str
    start_period: str
    end_period: str
    start_value: float
    end_value: float
    absolute_change: float
    percent_change: float | None = None
    largest_increase_period: str | None = None
    largest_increase: float | None = None
    largest_decrease_period: str | None = None
    largest_decrease: float | None = None
    anomaly_periods: tuple[str, ...] = ()
    missing_periods: tuple[str, ...] = ()
    suspected_partial_periods: tuple[str, ...] = ()
    valid_comparison_count: int = Field(ge=0)
    points: tuple[TimeSeriesPoint, ...]
    limitations: tuple[str, ...] = ()


DeterministicAnalysis = DistributionAnalysis | TimeSeriesAnalysis


class AnalysisNarrative(StrictModel):
    """Evidence-constrained model synthesis returned to the caller."""

    summary: str = Field(min_length=1, max_length=4000)
    findings: tuple[str, ...] = Field(min_length=1, max_length=10)
    limitations: tuple[str, ...] = Field(min_length=1, max_length=10)


class AgentAnalysisResult(StrictModel):
    """Complete audit envelope for one successful agent execution."""

    run_id: UUID
    status: RunStatus
    question: str
    started_at: datetime
    completed_at: datetime
    duration_ms: float = Field(ge=0)
    model_name: str
    prompt_versions: tuple[str, ...]
    schema_tables: tuple[str, ...]
    plan: AnalysisPlan
    sql_candidate: SQLCandidate
    sql_validation: SQLValidationResult
    sql_retry_count: int = Field(default=0, ge=0)
    query_result: QueryExecutionResult
    python_profile: QueryResultProfile
    deterministic_analyses: tuple[DeterministicAnalysis, ...]
    generated_python_analysis: GeneratedPythonAnalysis | None = None
    narrative: AnalysisNarrative
