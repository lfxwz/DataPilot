"""LLM synthesis constrained to executed query evidence."""

import json

from pydantic import ValidationError

from datapilot.adapters.llm.errors import LLMResponseValidationError
from datapilot.domain.agent import (
    AnalysisNarrative,
    DeterministicAnalysis,
    QueryResultProfile,
)
from datapilot.domain.analysis import AnalysisPlan, AnalysisRequest
from datapilot.domain.generated_python import GeneratedPythonAnalysis
from datapilot.domain.query import QueryExecutionResult
from datapilot.prompts.synthesis import SYSTEM_PROMPT
from datapilot.services.planning import StructuredLLM


class AnalysisSynthesizer:
    """Create a typed narrative from bounded, observed evidence only."""

    def __init__(self, client: StructuredLLM, *, preview_rows: int = 20) -> None:
        if preview_rows < 1:
            raise ValueError("preview_rows must be positive")
        self._client = client
        self._preview_rows = preview_rows

    def synthesize(
        self,
        *,
        request: AnalysisRequest,
        plan: AnalysisPlan,
        normalized_sql: str,
        result: QueryExecutionResult,
        profile: QueryResultProfile,
        deterministic_analyses: tuple[DeterministicAnalysis, ...],
        generated_python_analysis: GeneratedPythonAnalysis | None = None,
    ) -> AnalysisNarrative:
        payload = {
            "question": request.question,
            "analysis_objective": plan.objective,
            "executed_sql": normalized_sql,
            "query_metadata": {
                "columns": result.columns,
                "row_count": result.row_count,
                "truncated": result.truncated,
                "estimated_cost": result.plan.estimated_cost,
            },
            "python_profile": profile.model_dump(mode="json"),
            "deterministic_analyses": [
                analysis.model_dump(mode="json") for analysis in deterministic_analyses
            ],
            "generated_python_analysis": (
                generated_python_analysis.model_dump(mode="json", exclude={"generated_code"})
                if generated_python_analysis is not None
                else None
            ),
            "result_preview": [
                dict(zip(result.columns, row, strict=True))
                for row in result.rows[: self._preview_rows]
            ],
            "output_json_schema": AnalysisNarrative.model_json_schema(),
        }
        completion = self._client.complete_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=json.dumps(payload, ensure_ascii=False, default=str),
        )
        try:
            return AnalysisNarrative.model_validate(completion.data)
        except ValidationError as exc:
            raise LLMResponseValidationError(
                "The synthesis output did not satisfy the AnalysisNarrative contract."
            ) from exc
