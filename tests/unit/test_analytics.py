"""Numerical tests for deterministic business-analysis recipes."""

import pytest
from pydantic import ValidationError

from datapilot.domain.analytics import (
    AnalysisType,
    ContributionAnalysisSpec,
    GroupComparison,
    TwoProportionTestSpec,
)
from datapilot.services.analytics import AnalyticsEngine


def test_two_proportion_test_returns_reproducible_statistics() -> None:
    result = AnalyticsEngine().run(
        TwoProportionTestSpec(
            analysis_type=AnalysisType.TWO_PROPORTION_TEST,
            group_a_label="campaign_a",
            group_a_successes=120,
            group_a_trials=1000,
            group_b_label="campaign_b",
            group_b_successes=90,
            group_b_trials=1000,
        )
    )

    assert result.group_a_rate == pytest.approx(0.12)
    assert result.group_b_rate == pytest.approx(0.09)
    assert result.absolute_difference == pytest.approx(0.03)
    assert result.z_statistic == pytest.approx(2.188, abs=0.001)
    assert result.p_value == pytest.approx(0.0287, abs=0.0001)
    assert result.confidence_interval[0] > 0


def test_two_proportion_spec_rejects_impossible_counts() -> None:
    with pytest.raises(ValidationError, match="successes cannot exceed trials"):
        TwoProportionTestSpec(
            analysis_type=AnalysisType.TWO_PROPORTION_TEST,
            group_a_label="a",
            group_a_successes=11,
            group_a_trials=10,
            group_b_label="b",
            group_b_successes=5,
            group_b_trials=10,
        )


def test_two_proportion_test_rejects_zero_variance() -> None:
    task = TwoProportionTestSpec(
        analysis_type=AnalysisType.TWO_PROPORTION_TEST,
        group_a_label="a",
        group_a_successes=0,
        group_a_trials=100,
        group_b_label="b",
        group_b_successes=0,
        group_b_trials=100,
    )

    with pytest.raises(ValueError, match="pooled variance is zero"):
        AnalyticsEngine().run(task)


def test_contribution_analysis_ranks_largest_driver_first() -> None:
    result = AnalyticsEngine().run(
        ContributionAnalysisSpec(
            analysis_type=AnalysisType.CONTRIBUTION_ANALYSIS,
            metric_name="item_revenue",
            groups=(
                GroupComparison(label="organic", current_value=80, baseline_value=100),
                GroupComparison(label="paid", current_value=130, baseline_value=100),
                GroupComparison(label="affiliate", current_value=90, baseline_value=100),
            ),
        )
    )

    assert result.current_total == 300
    assert result.baseline_total == 300
    assert result.total_change == 0
    assert result.drivers[0].label == "paid"
    assert all(driver.contribution_share is None for driver in result.drivers)
