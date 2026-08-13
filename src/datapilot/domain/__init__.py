"""Domain contracts shared by workflows, tools, and API adapters."""

from datapilot.domain.agent import AgentAnalysisResult
from datapilot.domain.analysis import AnalysisPlan, AnalysisRequest, AnalysisStep
from datapilot.domain.analytics import AnalyticsResult, AnalyticsTask
from datapilot.domain.evidence import ArtifactRef, Evidence
from datapilot.domain.query import QueryExecutionResult, QueryPlanSummary
from datapilot.domain.schema import SchemaSnapshot, TableMetadata
from datapilot.domain.sql import SQLCandidate, SQLValidationResult

__all__ = [
    "AgentAnalysisResult",
    "AnalysisPlan",
    "AnalysisRequest",
    "AnalysisStep",
    "AnalyticsResult",
    "AnalyticsTask",
    "ArtifactRef",
    "Evidence",
    "QueryExecutionResult",
    "QueryPlanSummary",
    "SQLCandidate",
    "SQLValidationResult",
    "SchemaSnapshot",
    "TableMetadata",
]
