"""Deterministic contribution decomposition for business metrics."""

from datapilot.domain.analytics import (
    AnalysisType,
    ContributionAnalysisResult,
    ContributionAnalysisSpec,
    ContributionDriver,
)


def run_contribution_analysis(
    spec: ContributionAnalysisSpec,
) -> ContributionAnalysisResult:
    """Decompose an additive metric change across mutually exclusive groups."""

    current_total = sum(group.current_value for group in spec.groups)
    baseline_total = sum(group.baseline_value for group in spec.groups)
    total_change = current_total - baseline_total

    drivers = tuple(
        sorted(
            (
                ContributionDriver(
                    label=group.label,
                    current_value=group.current_value,
                    baseline_value=group.baseline_value,
                    absolute_change=group.current_value - group.baseline_value,
                    contribution_share=(
                        (group.current_value - group.baseline_value) / total_change
                        if total_change != 0
                        else None
                    ),
                )
                for group in spec.groups
            ),
            key=lambda driver: abs(driver.absolute_change),
            reverse=True,
        )
    )

    return ContributionAnalysisResult(
        analysis_type=AnalysisType.CONTRIBUTION_ANALYSIS,
        metric_name=spec.metric_name,
        current_total=current_total,
        baseline_total=baseline_total,
        total_change=total_change,
        drivers=drivers,
        limitations=(
            "Groups must be mutually exclusive and collectively cover the compared totals.",
            "Contribution decomposition describes arithmetic drivers, not causal effects.",
        ),
    )
