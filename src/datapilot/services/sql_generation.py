"""LLM SQL generation constrained by typed inputs and deterministic downstream policy."""

import json
from collections.abc import Mapping

from pydantic import ValidationError

from datapilot.adapters.llm.errors import LLMResponseValidationError
from datapilot.domain.analysis import AnalysisPlan, AnalysisRequest
from datapilot.domain.schema import SchemaSnapshot
from datapilot.domain.sql import SQLCandidate
from datapilot.prompts.sql_generator import SYSTEM_PROMPT
from datapilot.services.planning import StructuredLLM


class SQLGenerator:
    """Generate a typed SQL candidate; this class never executes SQL."""

    def __init__(self, client: StructuredLLM, *, dialect: str = "postgres") -> None:
        self._client = client
        self._dialect = dialect

    def generate(
        self,
        request: AnalysisRequest,
        plan: AnalysisPlan,
        schema: SchemaSnapshot,
    ) -> SQLCandidate:
        payload = {
            "question": request.question,
            "analysis_plan": plan.model_dump(mode="json"),
            "database_schema": self._schema_context(schema),
            "dialect": self._dialect,
            "output_json_schema": SQLCandidate.model_json_schema(),
        }
        return self._generate_candidate(payload)

    def repair(
        self,
        request: AnalysisRequest,
        plan: AnalysisPlan,
        schema: SchemaSnapshot,
        *,
        failed_candidate: SQLCandidate,
        database_error: str,
        attempt: int,
    ) -> SQLCandidate:
        """Generate a complete replacement after PostgreSQL rejects a candidate."""

        payload = {
            "question": request.question,
            "analysis_plan": plan.model_dump(mode="json"),
            "database_schema": self._schema_context(schema),
            "dialect": self._dialect,
            "failed_sql": failed_candidate.sql,
            "database_error": database_error,
            "repair_attempt": attempt,
            "repair_instruction": (
                "Return a corrected complete SQL statement. Use the supplied schema as the "
                "source of truth, fix the database error, and do not explain the correction."
            ),
            "output_json_schema": SQLCandidate.model_json_schema(),
        }
        return self._generate_candidate(payload)

    @staticmethod
    def _schema_context(schema: SchemaSnapshot) -> dict[str, object]:
        return {
            "database_name": schema.database_name,
            "captured_at": schema.captured_at.isoformat(),
            "tables": [
                {
                    **table.model_dump(mode="json"),
                    "qualified_name": table.qualified_name,
                }
                for table in schema.tables
            ],
        }

    def _generate_candidate(self, payload: Mapping[str, object]) -> SQLCandidate:
        completion = self._client.complete_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=json.dumps(payload, ensure_ascii=False),
        )
        candidate_data = dict(completion.data)
        candidate_data["dialect"] = self._dialect
        try:
            return SQLCandidate.model_validate(candidate_data)
        except ValidationError as exc:
            raise LLMResponseValidationError(
                "The SQL generator output did not satisfy the SQLCandidate contract."
            ) from exc
