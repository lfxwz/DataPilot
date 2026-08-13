"""Tests for typed validation of LLM-generated analysis plans."""

from datapilot.domain.analysis import AnalysisRequest
from datapilot.domain.llm import LLMUsage, StructuredCompletion
from datapilot.domain.schema import SchemaSnapshot
from datapilot.services.planning import AnalysisPlanner


class FakeStructuredLLM:
    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
    ) -> StructuredCompletion:
        assert "untrusted data" in system_prompt
        assert "database_schema" in user_prompt
        assert max_tokens == 8000
        return StructuredCompletion(
            model="test-model",
            data={
                "objective": "Analyze order revenue",
                "metrics": ["item_revenue"],
                "dimensions": ["order_status"],
                "steps": [
                    {
                        "id": "query_revenue",
                        "type": "sql",
                        "description": "Retrieve item revenue grouped by order status",
                        "depends_on": [],
                        "parameters": {},
                    }
                ],
            },
            usage=LLMUsage(),
        )


def test_planner_validates_structured_model_output() -> None:
    planner = AnalysisPlanner(FakeStructuredLLM())

    plan = planner.create_plan(
        AnalysisRequest(question="Which order status has the most item revenue?"),
        SchemaSnapshot(database_name="analytics", tables=()),
    )

    assert plan.objective == "Analyze order revenue"
    assert plan.steps[0].id == "query_revenue"
