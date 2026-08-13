"""Deterministic analytics recipe endpoint."""

from fastapi import APIRouter, HTTPException, status

from datapilot.domain.analytics import AnalyticsResult, AnalyticsTask
from datapilot.services.analytics import AnalyticsEngine

router = APIRouter(prefix="/analysis", tags=["analysis"])
engine = AnalyticsEngine()


@router.post("/run", response_model=AnalyticsResult)
def run_analysis(task: AnalyticsTask) -> AnalyticsResult:
    """Run one validated recipe without arbitrary code execution."""

    try:
        return engine.run(task)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
