"""Read-only query planning and execution contracts."""

from typing import Any

from pydantic import Field

from datapilot.domain.common import StrictModel


class QueryPlanSummary(StrictModel):
    node_type: str = Field(min_length=1, max_length=255)
    estimated_cost: float = Field(ge=0)
    estimated_rows: int = Field(ge=0)


class QueryExecutionResult(StrictModel):
    """Bounded query output suitable for API serialization or artifact storage."""

    query_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    row_count: int = Field(ge=0)
    truncated: bool
    duration_ms: float = Field(ge=0)
    plan: QueryPlanSummary
