"""Statistical tests implemented with explicit formulas and assumptions."""

from math import asin, sqrt
from statistics import NormalDist

from datapilot.domain.analytics import (
    AnalysisType,
    TwoProportionTestResult,
    TwoProportionTestSpec,
)


def run_two_proportion_test(spec: TwoProportionTestSpec) -> TwoProportionTestResult:
    """Run a two-sided pooled z-test and an unpooled Wald interval.

    The pooled standard error is used for the null-hypothesis test. The confidence
    interval uses the unpooled standard error for the observed rate difference.
    """

    rate_a = spec.group_a_successes / spec.group_a_trials
    rate_b = spec.group_b_successes / spec.group_b_trials
    difference = rate_a - rate_b
    pooled_rate = (spec.group_a_successes + spec.group_b_successes) / (
        spec.group_a_trials + spec.group_b_trials
    )
    pooled_standard_error = sqrt(
        pooled_rate * (1 - pooled_rate) * (1 / spec.group_a_trials + 1 / spec.group_b_trials)
    )
    if pooled_standard_error == 0:
        raise ValueError("the pooled variance is zero; the z-test is undefined")

    z_statistic = difference / pooled_standard_error
    normal = NormalDist()
    p_value = 2 * (1 - normal.cdf(abs(z_statistic)))
    critical_value = normal.inv_cdf(0.5 + spec.confidence_level / 2)
    interval_standard_error = sqrt(
        rate_a * (1 - rate_a) / spec.group_a_trials + rate_b * (1 - rate_b) / spec.group_b_trials
    )
    confidence_interval = (
        difference - critical_value * interval_standard_error,
        difference + critical_value * interval_standard_error,
    )
    relative_lift = difference / rate_b if rate_b != 0 else None
    effect_size = 2 * (asin(sqrt(rate_a)) - asin(sqrt(rate_b)))

    return TwoProportionTestResult(
        analysis_type=AnalysisType.TWO_PROPORTION_TEST,
        group_a_rate=rate_a,
        group_b_rate=rate_b,
        absolute_difference=difference,
        relative_lift=relative_lift,
        z_statistic=z_statistic,
        p_value=p_value,
        confidence_interval=confidence_interval,
        effect_size_cohens_h=effect_size,
        confidence_level=spec.confidence_level,
        assumptions=(
            "Observations are independent within and between groups.",
            "The normal approximation is adequate for both binomial samples.",
            "The reported association is not causal without randomized assignment.",
        ),
    )
