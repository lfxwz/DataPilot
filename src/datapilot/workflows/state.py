"""Checkpoint-safe state channels for DataPilot workflows."""

import operator
from typing import Annotated, TypedDict

from datapilot.domain.analysis import AnalysisPlan, AnalysisRequest
from datapilot.domain.common import ErrorInfo, RunContext, RunStatus
from datapilot.domain.evidence import ArtifactRef, Evidence
from datapilot.domain.sql import SQLCandidate, SQLValidationResult


class RunState(TypedDict, total=False):
    """Small workflow state; large datasets remain in an artifact store."""

    context: RunContext
    request: AnalysisRequest
    status: RunStatus
    plan: AnalysisPlan
    sql_candidate: SQLCandidate
    sql_validation: SQLValidationResult
    artifacts: Annotated[list[ArtifactRef], operator.add]
    evidence: Annotated[list[Evidence], operator.add]
    retry_count: int
    error: ErrorInfo | None
