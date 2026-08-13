"""Tests for the analysis-plan intermediate representation."""

import pytest
from pydantic import ValidationError

from datapilot.domain.analysis import AnalysisPlan, AnalysisStep, StepType


def test_analysis_plan_accepts_valid_dependency_graph() -> None:
    plan = AnalysisPlan(
        objective="Explain quarterly revenue decline",
        metrics=("item_revenue",),
        steps=(
            AnalysisStep(
                id="query_sales",
                type=StepType.SQL,
                description="Retrieve quarterly sales",
            ),
            AnalysisStep(
                id="analyze_drivers",
                type=StepType.PYTHON_ANALYSIS,
                description="Decompose the change by channel",
                depends_on=("query_sales",),
            ),
        ),
    )

    assert plan.steps[1].depends_on == ("query_sales",)


def test_analysis_plan_rejects_unknown_dependency() -> None:
    with pytest.raises(ValidationError, match="unknown dependencies"):
        AnalysisPlan(
            objective="Analyze campaign conversion",
            steps=(
                AnalysisStep(
                    id="test_conversion",
                    type=StepType.PYTHON_ANALYSIS,
                    description="Compare campaign conversion rates",
                    depends_on=("missing_query",),
                ),
            ),
        )


def test_analysis_plan_rejects_dependency_cycle() -> None:
    with pytest.raises(ValidationError, match="dependency cycle"):
        AnalysisPlan(
            objective="Analyze campaign conversion",
            steps=(
                AnalysisStep(
                    id="first_step",
                    type=StepType.SQL,
                    description="First cyclic step",
                    depends_on=("second_step",),
                ),
                AnalysisStep(
                    id="second_step",
                    type=StepType.PYTHON_ANALYSIS,
                    description="Second cyclic step",
                    depends_on=("first_step",),
                ),
            ),
        )
