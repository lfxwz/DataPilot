"""Typed inputs and outputs for deterministic analytical recipes."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from datapilot.domain.common import StrictModel


class AnalysisType(StrEnum):
    TWO_PROPORTION_TEST = "two_proportion_test"
    CONTRIBUTION_ANALYSIS = "contribution_analysis"


class TwoProportionTestSpec(StrictModel):
    analysis_type: Literal[AnalysisType.TWO_PROPORTION_TEST]
    group_a_label: str = Field(min_length=1, max_length=200)
    group_a_successes: int = Field(ge=0)
    group_a_trials: int = Field(gt=0)
    group_b_label: str = Field(min_length=1, max_length=200)
    group_b_successes: int = Field(ge=0)
    group_b_trials: int = Field(gt=0)
    confidence_level: float = Field(default=0.95, gt=0.5, lt=1.0)

    @model_validator(mode="after")
    def validate_success_counts(self) -> "TwoProportionTestSpec":
        if self.group_a_successes > self.group_a_trials:
            raise ValueError("group A successes cannot exceed trials")
        if self.group_b_successes > self.group_b_trials:
            raise ValueError("group B successes cannot exceed trials")
        return self


class TwoProportionTestResult(StrictModel):
    analysis_type: Literal[AnalysisType.TWO_PROPORTION_TEST]
    group_a_rate: float = Field(ge=0, le=1)
    group_b_rate: float = Field(ge=0, le=1)
    absolute_difference: float = Field(ge=-1, le=1)
    relative_lift: float | None
    z_statistic: float
    p_value: float = Field(ge=0, le=1)
    confidence_interval: tuple[float, float]
    effect_size_cohens_h: float
    confidence_level: float
    assumptions: tuple[str, ...]


class GroupComparison(StrictModel):
    label: str = Field(min_length=1, max_length=200)
    current_value: float
    baseline_value: float


class ContributionAnalysisSpec(StrictModel):
    analysis_type: Literal[AnalysisType.CONTRIBUTION_ANALYSIS]
    metric_name: str = Field(min_length=1, max_length=200)
    groups: tuple[GroupComparison, ...] = Field(min_length=1, max_length=10_000)


class ContributionDriver(StrictModel):
    label: str
    current_value: float
    baseline_value: float
    absolute_change: float
    contribution_share: float | None


class ContributionAnalysisResult(StrictModel):
    analysis_type: Literal[AnalysisType.CONTRIBUTION_ANALYSIS]
    metric_name: str
    current_total: float
    baseline_total: float
    total_change: float
    drivers: tuple[ContributionDriver, ...]
    limitations: tuple[str, ...]


AnalyticsTask = Annotated[
    TwoProportionTestSpec | ContributionAnalysisSpec,
    Field(discriminator="analysis_type"),
]
AnalyticsResult = TwoProportionTestResult | ContributionAnalysisResult
