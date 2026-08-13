"""Closed recipe registry; arbitrary Python execution is intentionally excluded."""

from typing import assert_never

from datapilot.domain.analytics import (
    AnalyticsResult,
    AnalyticsTask,
    ContributionAnalysisSpec,
    TwoProportionTestSpec,
)
from datapilot.services.analytics.contribution import run_contribution_analysis
from datapilot.services.analytics.statistics import run_two_proportion_test


class AnalyticsEngine:
    """Dispatch validated specifications to deterministic analytical functions."""

    def run(self, task: AnalyticsTask) -> AnalyticsResult:
        if isinstance(task, TwoProportionTestSpec):
            return run_two_proportion_test(task)
        if isinstance(task, ContributionAnalysisSpec):
            return run_contribution_analysis(task)
        assert_never(task)
