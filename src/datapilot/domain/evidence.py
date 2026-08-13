"""Traceable artifacts and evidence-backed findings."""

from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field

from datapilot.domain.common import StrictModel


class ArtifactType(StrEnum):
    QUERY_RESULT = "query_result"
    DATASET = "dataset"
    STATISTICAL_RESULT = "statistical_result"
    CHART = "chart"
    REPORT = "report"


class ClaimType(StrEnum):
    DESCRIPTIVE = "descriptive"
    ASSOCIATIONAL = "associational"
    INFERENTIAL = "inferential"
    CAUSAL = "causal"


class ArtifactRef(StrictModel):
    """Small checkpoint-safe reference to externally stored run output."""

    artifact_id: UUID = Field(default_factory=uuid4)
    type: ArtifactType
    uri: str = Field(min_length=1, max_length=2000)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class Evidence(StrictModel):
    """A finding linked to the artifacts that support it."""

    finding: str = Field(min_length=1, max_length=2000)
    claim_type: ClaimType
    artifact_ids: tuple[UUID, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = ()
