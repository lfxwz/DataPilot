"""LLM-backed planner constrained by typed analysis contracts."""

import json
from typing import Protocol

from pydantic import ValidationError

from datapilot.adapters.llm.errors import LLMResponseValidationError
from datapilot.domain.analysis import AnalysisPlan, AnalysisRequest
from datapilot.domain.llm import StructuredCompletion
from datapilot.domain.schema import SchemaSnapshot
from datapilot.prompts.analysis_planner import SYSTEM_PROMPT


class StructuredLLM(Protocol):
    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
    ) -> StructuredCompletion: ...


class AnalysisPlanner:
    """Build a validated analysis plan grounded in a schema snapshot."""

    def __init__(self, client: StructuredLLM) -> None:
        self._client = client

    def create_plan(
        self,
        request: AnalysisRequest,
        schema: SchemaSnapshot,
    ) -> AnalysisPlan:
        user_payload = {
            "question": request.question,
            "requested_metrics": request.requested_metrics,
            "database_schema": schema.model_dump(mode="json"),
            "output_json_schema": AnalysisPlan.model_json_schema(),
        }
        completion = self._client.complete_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=json.dumps(user_payload, ensure_ascii=False),
            max_tokens=8000,
        )
        try:
            return AnalysisPlan.model_validate(completion.data)
        except ValidationError as exc:
            raise LLMResponseValidationError(
                "The planner output did not satisfy the AnalysisPlan contract."
            ) from exc
