"""Numerical tests for deterministic analyses selected from SQL result types."""

from datetime import date

import pytest

from datapilot.domain.agent import DistributionAnalysis, TimeSeriesAnalysis
from datapilot.domain.query import QueryExecutionResult, QueryPlanSummary
from datapilot.services.deterministic_analysis import DeterministicAnalysisEngine


def result(
    columns: tuple[str, ...],
    rows: tuple[tuple[object, ...], ...],
    *,
    truncated: bool = False,
) -> QueryExecutionResult:
    return QueryExecutionResult(
        query_hash="d" * 64,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        duration_ms=1,
        plan=QueryPlanSummary(node_type="Result", estimated_cost=1, estimated_rows=len(rows)),
    )


def test_distribution_computes_shares_dense_ranks_and_concentration() -> None:
    analysis = DeterministicAnalysisEngine().analyze(
        result(
            ("status", "order_count"),
            (("delivered", 80), ("shipped", 10), ("canceled", 10)),
        )
    )[0]

    assert isinstance(analysis, DistributionAnalysis)
    assert analysis.total == 100
    assert analysis.top_1_share == pytest.approx(0.8)
    assert analysis.top_3_share == pytest.approx(1)
    assert [point.rank for point in analysis.points] == [1, 2, 2]
    assert analysis.points[-1].cumulative_share == pytest.approx(1)


def test_distribution_aggregates_duplicate_labels_and_suppresses_invalid_shares() -> None:
    analysis = DeterministicAnalysisEngine().analyze(
        result(("category", "change"), (("a", 4), ("a", 1), ("b", -2)), truncated=True)
    )[0]

    assert isinstance(analysis, DistributionAnalysis)
    assert [(point.label, point.value) for point in analysis.points] == [("a", 5), ("b", -2)]
    assert analysis.top_1_share is None
    assert any("truncated" in limitation for limitation in analysis.limitations)


def test_time_series_computes_changes_growth_extremes_and_anomaly_flags() -> None:
    analysis = DeterministicAnalysisEngine(anomaly_z_threshold=1.0).analyze(
        result(
            ("purchase_month", "order_count"),
            (
                (date(2024, 3, 1), 150),
                (date(2024, 1, 1), 100),
                (date(2024, 2, 1), 110),
                (date(2024, 4, 1), 90),
            ),
        )
    )[0]

    assert isinstance(analysis, TimeSeriesAnalysis)
    assert [point.period for point in analysis.points] == [
        "2024-01-01",
        "2024-02-01",
        "2024-03-01",
        "2024-04-01",
    ]
    assert analysis.start_period == "2024-01-01"
    assert analysis.end_period == "2024-04-01"
    assert analysis.absolute_change == -10
    assert analysis.percent_change == pytest.approx(-0.1)
    assert analysis.largest_increase_period == "2024-03-01"
    assert analysis.largest_increase == 40
    assert analysis.largest_decrease_period == "2024-04-01"
    assert analysis.largest_decrease == -60
    assert analysis.anomaly_periods
    assert analysis.valid_comparison_count == 3


def test_time_series_marks_percent_change_after_zero_as_undefined() -> None:
    analysis = DeterministicAnalysisEngine().analyze(
        result(("month", "value"), (("2024-01-01", 0), ("2024-02-01", 5)))
    )[0]

    assert isinstance(analysis, TimeSeriesAnalysis)
    assert analysis.percent_change is None
    assert analysis.points[1].percent_change is None
    assert any("zero-valued" in limitation for limitation in analysis.limitations)


def test_engine_returns_no_analysis_without_dimension_and_metric() -> None:
    engine = DeterministicAnalysisEngine()

    assert engine.analyze(result(("count",), ((1,),))) == ()
    assert engine.analyze(result(("category", "value"), ())) == ()
    with pytest.raises(ValueError, match="positive"):
        DeterministicAnalysisEngine(anomaly_z_threshold=0)


def test_engine_does_not_reanalyze_sql_derived_rank_or_percentage_columns() -> None:
    analyses = DeterministicAnalysisEngine().analyze(
        result(
            ("status", "order_count", "percentage", "status_rank"),
            (("delivered", 80, 80.0, 1), ("shipped", 20, 20.0, 2)),
        )
    )

    assert len(analyses) == 1
    assert analyses[0].metric_column == "order_count"


def test_time_series_excludes_gaps_and_suspected_partial_boundaries() -> None:
    analysis = DeterministicAnalysisEngine().analyze(
        result(
            ("order_month", "order_count"),
            (
                (date(2023, 12, 1), 2),
                (date(2024, 1, 1), 100),
                (date(2024, 3, 1), 130),
                (date(2024, 4, 1), 150),
                (date(2024, 5, 1), 3),
            ),
        )
    )[0]

    assert isinstance(analysis, TimeSeriesAnalysis)
    assert analysis.start_period == "2024-01-01"
    assert analysis.end_period == "2024-04-01"
    assert analysis.missing_periods == ("2024-02-01",)
    assert analysis.suspected_partial_periods == ("2023-12-01", "2024-05-01")
    assert analysis.valid_comparison_count == 1
    assert analysis.points[2].absolute_change is None
    assert analysis.points[3].absolute_change == 20
    assert analysis.points[4].absolute_change is None
