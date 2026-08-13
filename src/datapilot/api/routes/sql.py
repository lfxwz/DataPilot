"""SQL policy inspection endpoint used before any future execution path."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from datapilot.adapters.database.errors import (
    QueryBudgetExceededError,
    QueryPolicyError,
    ReadOnlyBoundaryError,
)
from datapilot.api.dependencies import (
    AnalyticsDatabaseDependency,
    QueryAPIEnabledDependency,
    SQLSafetyPolicyDependency,
)
from datapilot.domain.query import QueryExecutionResult
from datapilot.domain.sql import SQLCandidate, SQLValidationResult

router = APIRouter(prefix="/sql", tags=["sql"])


@router.post("/validate", response_model=SQLValidationResult)
def validate_sql(
    candidate: SQLCandidate,
    policy: SQLSafetyPolicyDependency,
) -> SQLValidationResult:
    """Validate and normalize SQL without contacting a database."""

    return policy.validate(candidate)


@router.post("/execute", response_model=QueryExecutionResult)
def execute_sql(
    candidate: SQLCandidate,
    database: AnalyticsDatabaseDependency,
    _: QueryAPIEnabledDependency,
) -> QueryExecutionResult:
    """Execute one policy-approved query against the read-only database role."""

    try:
        return database.execute(candidate)
    except QueryPolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except QueryBudgetExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except (ReadOnlyBoundaryError, SQLAlchemyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The analytical query could not be executed safely.",
        ) from exc
