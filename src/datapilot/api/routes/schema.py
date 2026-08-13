"""Schema catalog endpoints."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from datapilot.api.dependencies import (
    AnalyticsDatabaseDependency,
    QueryAPIEnabledDependency,
)
from datapilot.domain.schema import SchemaSnapshot

router = APIRouter(prefix="/schema", tags=["schema"])


@router.get("", response_model=SchemaSnapshot)
def inspect_schema(
    database: AnalyticsDatabaseDependency,
    _: QueryAPIEnabledDependency,
    schema_names: Annotated[list[str] | None, Query(min_length=1, max_length=10)] = None,
) -> SchemaSnapshot:
    """Return grounded metadata for explicitly requested schemas."""

    try:
        return database.inspect_schema(schema_names or ["olist"])
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Schema metadata is temporarily unavailable.",
        ) from exc
