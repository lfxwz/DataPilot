"""Natural-language analysis-agent endpoint."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy.exc import SQLAlchemyError

from datapilot.adapters.database.errors import (
    QueryBudgetExceededError,
    QueryPolicyError,
    ReadOnlyBoundaryError,
)
from datapilot.adapters.llm.errors import LLMProviderError, LLMResponseValidationError
from datapilot.adapters.sandbox.errors import GeneratedCodePolicyError, SandboxExecutionError
from datapilot.api.dependencies import (
    AgentAPIEnabledDependency,
    AnalysisAgentDependency,
    AnalysisRunRepositoryDependency,
)
from datapilot.domain.agent import AgentAnalysisResult
from datapilot.domain.analysis import AnalysisRequest
from datapilot.domain.run_history import AnalysisRunPage, AnalysisRunRecord
from datapilot.services.reports import render_markdown_report

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/runs", response_model=AnalysisRunPage)
def list_runs(
    _: AgentAPIEnabledDependency,
    repository: AnalysisRunRepositoryDependency,
    limit: int = Query(default=20, ge=1, le=100),
) -> AnalysisRunPage:
    """Return recent synchronous analysis runs without loading full result payloads."""

    return AnalysisRunPage(items=repository.list_runs(limit=limit), limit=limit)


@router.get("/runs/{run_id}", response_model=AnalysisRunRecord)
def get_run(
    run_id: UUID,
    _: AgentAPIEnabledDependency,
    repository: AnalysisRunRepositoryDependency,
) -> AnalysisRunRecord:
    """Return one durable success or safe failure audit record."""

    record = repository.get_run(run_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis run was not found.",
        )
    return record


@router.get("/runs/{run_id}/report", response_class=Response)
def download_report(
    run_id: UUID,
    _: AgentAPIEnabledDependency,
    repository: AnalysisRunRepositoryDependency,
) -> Response:
    """Download a validated Markdown report for one successful run."""

    record = repository.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Analysis run was not found.")
    record = AnalysisRunRecord.model_validate(record)
    if record.result is None:
        raise HTTPException(status_code=409, detail="This run has no successful report result.")
    report = render_markdown_report(record.result)
    return Response(
        content=report,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="datapilot-{run_id}.md"'},
    )


@router.post("/analyze", response_model=AgentAnalysisResult)
def analyze(
    request: AnalysisRequest,
    _: AgentAPIEnabledDependency,
    agent: AnalysisAgentDependency,
) -> AgentAnalysisResult:
    """Run one bounded, evidence-backed SQL and Python analysis."""

    try:
        return agent.analyze(request)
    except (QueryPolicyError, LLMResponseValidationError, GeneratedCodePolicyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except QueryBudgetExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The configured analysis model is temporarily unavailable.",
        ) from exc
    except SandboxExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except (ReadOnlyBoundaryError, SQLAlchemyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The analysis could not be executed safely against the database.",
        ) from exc
