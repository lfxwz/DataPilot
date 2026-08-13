"""Provider-neutral LLM request accounting contracts."""

from typing import Any

from pydantic import Field

from datapilot.domain.common import StrictModel


class LLMUsage(StrictModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class StructuredCompletion(StrictModel):
    model: str = Field(min_length=1, max_length=255)
    data: dict[str, Any]
    usage: LLMUsage
    provider_request_id: str | None = Field(default=None, max_length=500)
