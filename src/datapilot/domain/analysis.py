"""Contracts for plans produced by an LLM and executed by deterministic tools."""

from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from datapilot.domain.common import StrictModel


class StepType(StrEnum):
    SQL = "sql"
    PYTHON_ANALYSIS = "python_analysis"
    VISUALIZATION = "visualization"
    SYNTHESIS = "synthesis"


class PythonExecutionMode(StrEnum):
    """Execution class selected by the planner for a Python analysis step."""

    VERIFIED = "verified"
    GENERATED_ANALYTICS = "generated_analytics"
    GENERATED_DEEP_LEARNING = "generated_deep_learning"


class AnalysisRequest(StrictModel):
    """User request after API-level validation."""

    question: str = Field(min_length=3, max_length=4000)
    session_id: str | None = Field(default=None, max_length=200)
    requested_metrics: tuple[str, ...] = ()
    allow_generated_python: bool = True
    include_visualizations: bool = True
    include_report: bool = True


class AnalysisStep(StrictModel):
    """A single executable step in an analysis dependency graph."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    type: StepType
    description: str = Field(min_length=3, max_length=500)
    depends_on: tuple[str, ...] = ()
    parameters: dict[str, Any] = Field(default_factory=dict)
    python_mode: PythonExecutionMode | None = None


class AnalysisPlan(StrictModel):
    """Validated intermediate representation between the LLM and tools."""

    objective: str = Field(min_length=3, max_length=1000)
    metrics: tuple[str, ...] = ()
    dimensions: tuple[str, ...] = ()
    steps: tuple[AnalysisStep, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_dependency_graph(self) -> "AnalysisPlan":
        """Reject duplicate IDs, missing dependencies, and dependency cycles."""

        step_ids = [step.id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("analysis step IDs must be unique")

        known_ids = set(step_ids)
        for step in self.steps:
            unknown = set(step.depends_on) - known_ids
            if unknown:
                raise ValueError(f"step {step.id!r} has unknown dependencies: {sorted(unknown)}")
            if step.id in step.depends_on:
                raise ValueError(f"step {step.id!r} cannot depend on itself")

        dependencies = {step.id: set(step.depends_on) for step in self.steps}
        pending = set(dependencies)
        while pending:
            ready = {step_id for step_id in pending if not dependencies[step_id] & pending}
            if not ready:
                raise ValueError("analysis plan contains a dependency cycle")
            pending -= ready
        return self
