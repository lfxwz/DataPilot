"""Contracts for model-generated Python executed outside the API process."""

from enum import StrEnum
from typing import TypeAlias

from pydantic import Field, field_validator, model_validator

from datapilot.domain.common import StrictModel

JsonScalar: TypeAlias = str | int | float | bool | None
JsonDiagnostic: TypeAlias = JsonScalar | list[JsonScalar]


class SandboxProfile(StrEnum):
    ANALYTICS = "analytics"
    DEEP_LEARNING = "deep_learning"


class ChartType(StrEnum):
    BAR = "bar"
    LINE = "line"
    SCATTER = "scatter"
    AREA = "area"
    HISTOGRAM = "histogram"
    BOX = "box"
    HEATMAP = "heatmap"


class ChartSeries(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    x: tuple[JsonScalar, ...] = Field(min_length=1, max_length=500)
    y: tuple[float, ...] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_equal_lengths(self) -> "ChartSeries":
        if len(self.x) != len(self.y):
            raise ValueError("chart series x and y lengths must match")
        return self


class ChartSpec(StrictModel):
    chart_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    chart_type: ChartType
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=500)
    x_label: str = Field(default="", max_length=100)
    y_label: str = Field(default="", max_length=100)
    series: tuple[ChartSeries, ...] = Field(min_length=1, max_length=10)


class GeneratedPythonProgram(StrictModel):
    """Code proposed by the model before local policy validation."""

    analysis_goal: str = Field(min_length=3, max_length=1000)
    profile: SandboxProfile
    code: str = Field(min_length=20, max_length=20_000)
    expected_outputs: tuple[str, ...] = Field(min_length=1, max_length=20)
    assumptions: tuple[str, ...] = Field(default=(), max_length=20)


class PythonPolicyIssue(StrictModel):
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=500)
    line: int | None = Field(default=None, ge=1)


class PythonPolicyValidation(StrictModel):
    accepted: bool
    code_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    issues: tuple[PythonPolicyIssue, ...] = ()


class GeneratedAnalysisOutput(StrictModel):
    """Small JSON-only result returned by generated code."""

    analysis_type: str = Field(min_length=1, max_length=100)
    summary_metrics: dict[str, JsonScalar] = Field(default_factory=dict)
    findings: tuple[str, ...] = Field(min_length=1, max_length=20)
    diagnostics: dict[str, JsonDiagnostic] = Field(default_factory=dict)
    limitations: tuple[str, ...] = Field(min_length=1, max_length=20)
    visualizations: tuple[ChartSpec, ...] = Field(default=(), max_length=4)
    report_markdown: str | None = Field(default=None, max_length=20_000)

    @field_validator("report_markdown")
    @classmethod
    def reject_executable_markdown(cls, value: str | None) -> str | None:
        if value is None:
            return None
        lowered = value.lower()
        forbidden = ("<script", "<iframe", "javascript:", "data:", "![")
        if any(token in lowered for token in forbidden):
            raise ValueError("report_markdown contains forbidden executable or embedded content")
        return value


class SandboxResourceLimits(StrictModel):
    timeout_seconds: int = Field(ge=1, le=300)
    memory_mb: int = Field(ge=128, le=16_384)
    cpu_count: float = Field(gt=0, le=16)
    network_disabled: bool = True
    read_only_root: bool = True


class GeneratedPythonAnalysis(StrictModel):
    """Auditable experimental result from an isolated generated-code run."""

    classification: str = "experimental_generated_code"
    profile: SandboxProfile
    analysis_goal: str
    generated_code: str
    policy: PythonPolicyValidation
    output: GeneratedAnalysisOutput
    duration_ms: float = Field(ge=0)
    stdout: str = Field(default="", max_length=4000)
    resource_limits: SandboxResourceLimits
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def require_accepted_policy(self) -> "GeneratedPythonAnalysis":
        if not self.policy.accepted:
            raise ValueError("executed generated code must have an accepted policy result")
        return self
