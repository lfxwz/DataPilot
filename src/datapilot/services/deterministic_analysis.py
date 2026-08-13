"""Deterministic distribution and time-series analysis over bounded query results."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from math import isfinite
from numbers import Real
from statistics import fmean, median, pstdev

from datapilot.domain.agent import (
    DeterministicAnalysis,
    DistributionAnalysis,
    DistributionPoint,
    TimeSeriesAnalysis,
    TimeSeriesPoint,
)
from datapilot.domain.query import QueryExecutionResult

_TIME_NAME_HINTS = ("date", "day", "week", "month", "quarter", "year", "period", "time")
_DERIVED_METRIC_NAME_HINTS = (
    "rank",
    "percent",
    "percentage",
    "share",
    "ratio",
    "rate",
    "cumulative",
    "z_score",
)


class DeterministicAnalysisEngine:
    """Select safe analyses from observed result types and compute all numeric claims."""

    def __init__(self, *, anomaly_z_threshold: float = 2.0) -> None:
        if anomaly_z_threshold <= 0:
            raise ValueError("anomaly_z_threshold must be positive")
        self._anomaly_z_threshold = anomaly_z_threshold

    def analyze(self, result: QueryExecutionResult) -> tuple[DeterministicAnalysis, ...]:
        if result.row_count == 0 or len(result.columns) < 2:
            return ()

        dimension_index = self._dimension_index(result)
        if dimension_index is None:
            return ()
        numeric_indices = self._numeric_indices(result, exclude=dimension_index)
        analyses: list[DeterministicAnalysis] = []
        for metric_index in numeric_indices:
            pairs = self._complete_pairs(result, dimension_index, metric_index)
            if not pairs:
                continue
            limitations = self._limitations(result, len(pairs))
            if self._is_time_dimension(result.columns[dimension_index], pairs):
                analyses.append(
                    self._time_series(
                        result.columns[dimension_index],
                        result.columns[metric_index],
                        pairs,
                        limitations,
                    )
                )
            else:
                analyses.append(
                    self._distribution(
                        result.columns[dimension_index],
                        result.columns[metric_index],
                        pairs,
                        limitations,
                    )
                )
        return tuple(analyses)

    @staticmethod
    def _dimension_index(result: QueryExecutionResult) -> int | None:
        for index in range(len(result.columns)):
            values = tuple(row[index] for row in result.rows if row[index] is not None)
            if values and not all(
                DeterministicAnalysisEngine._is_number(value) for value in values
            ):
                return index
        return None

    @staticmethod
    def _numeric_indices(result: QueryExecutionResult, *, exclude: int) -> tuple[int, ...]:
        indices: list[int] = []
        for index in range(len(result.columns)):
            if index == exclude:
                continue
            column_name = result.columns[index].casefold()
            if any(hint in column_name for hint in _DERIVED_METRIC_NAME_HINTS):
                continue
            values = tuple(row[index] for row in result.rows if row[index] is not None)
            if values and all(DeterministicAnalysisEngine._is_number(value) for value in values):
                indices.append(index)
        return tuple(indices)

    @staticmethod
    def _complete_pairs(
        result: QueryExecutionResult,
        dimension_index: int,
        metric_index: int,
    ) -> tuple[tuple[object, float], ...]:
        pairs: list[tuple[object, float]] = []
        for row in result.rows:
            dimension = row[dimension_index]
            metric = row[metric_index]
            if dimension is None or not DeterministicAnalysisEngine._is_number(metric):
                continue
            numeric = float(metric)
            if isfinite(numeric):
                pairs.append((dimension, numeric))
        return tuple(pairs)

    @staticmethod
    def _limitations(result: QueryExecutionResult, analyzed_rows: int) -> tuple[str, ...]:
        limitations: list[str] = ["Descriptive analysis only; no causal inference is performed."]
        if result.truncated:
            limitations.append(
                "The SQL result was truncated; computed values cover returned rows only."
            )
        if analyzed_rows < result.row_count:
            limitations.append(
                "Rows with null or non-finite dimension/metric values were excluded."
            )
        return tuple(limitations)

    @staticmethod
    def _is_time_dimension(
        column_name: str,
        pairs: tuple[tuple[object, float], ...],
    ) -> bool:
        if any(isinstance(value, (date, datetime)) for value, _ in pairs):
            return True
        if not any(hint in column_name.casefold() for hint in _TIME_NAME_HINTS):
            return False
        return all(
            DeterministicAnalysisEngine._parse_period(value) is not None for value, _ in pairs
        )

    @staticmethod
    def _distribution(
        dimension_column: str,
        metric_column: str,
        pairs: tuple[tuple[object, float], ...],
        limitations: tuple[str, ...],
    ) -> DistributionAnalysis:
        aggregated: dict[str, float] = {}
        for label, value in pairs:
            key = str(label)
            aggregated[key] = aggregated.get(key, 0.0) + value
        ordered = sorted(aggregated.items(), key=lambda pair: (-pair[1], pair[0]))
        total = sum(value for _, value in ordered)
        supports_shares = total > 0 and all(value >= 0 for _, value in ordered)
        cumulative = 0.0
        points: list[DistributionPoint] = []
        previous_value: float | None = None
        current_rank = 0
        for position, (label, value) in enumerate(ordered, start=1):
            if previous_value is None or value != previous_value:
                current_rank = position
            share = value / total if supports_shares else None
            if share is not None:
                cumulative += share
            points.append(
                DistributionPoint(
                    label=str(label),
                    value=value,
                    rank=current_rank,
                    share=share,
                    cumulative_share=min(cumulative, 1.0) if share is not None else None,
                )
            )
            previous_value = value

        analysis_limitations = list(limitations)
        if not supports_shares:
            analysis_limitations.append(
                "Shares were not computed because values include negatives "
                "or have a non-positive total."
            )
        return DistributionAnalysis(
            dimension_column=dimension_column,
            metric_column=metric_column,
            total=total,
            top_1_share=points[0].share if points else None,
            top_3_share=(
                sum(point.share or 0.0 for point in points[:3]) if supports_shares else None
            ),
            points=tuple(points),
            limitations=tuple(analysis_limitations),
        )

    def _time_series(
        self,
        dimension_column: str,
        metric_column: str,
        pairs: tuple[tuple[object, float], ...],
        limitations: tuple[str, ...],
    ) -> TimeSeriesAnalysis:
        ordered = sorted(pairs, key=lambda pair: self._period_sort_key(pair[0]))
        partial_indices = self._suspected_partial_indices(ordered)
        missing_periods = self._missing_months(dimension_column, ordered)
        comparison_changes: dict[int, float] = {}
        for index in range(1, len(ordered)):
            if (
                index not in partial_indices
                and index - 1 not in partial_indices
                and self._is_consecutive_period(
                    dimension_column,
                    ordered[index - 1][0],
                    ordered[index][0],
                )
            ):
                comparison_changes[index] = ordered[index][1] - ordered[index - 1][1]
        changes = tuple(comparison_changes.values())
        change_mean = fmean(changes) if changes else 0.0
        change_std = pstdev(changes) if len(changes) >= 2 else 0.0
        points: list[TimeSeriesPoint] = []
        for index, (period, value) in enumerate(ordered):
            comparison_valid = index in comparison_changes
            absolute_change = comparison_changes.get(index)
            previous = ordered[index - 1][1] if comparison_valid else None
            percent_change = (
                None
                if absolute_change is None or previous is None or previous == 0
                else absolute_change / abs(previous)
            )
            z_score = (
                None
                if absolute_change is None or change_std == 0
                else (absolute_change - change_mean) / change_std
            )
            points.append(
                TimeSeriesPoint(
                    period=self._period_label(period),
                    value=value,
                    comparison_valid=comparison_valid,
                    suspected_partial_period=index in partial_indices,
                    absolute_change=absolute_change,
                    percent_change=percent_change,
                    change_z_score=z_score,
                    is_anomaly=z_score is not None and abs(z_score) >= self._anomaly_z_threshold,
                )
            )

        increases = [point for point in points if (point.absolute_change or 0.0) > 0]
        decreases = [point for point in points if (point.absolute_change or 0.0) < 0]
        largest_increase = max(
            increases,
            key=lambda point: point.absolute_change or 0.0,
            default=None,
        )
        largest_decrease = min(
            decreases,
            key=lambda point: point.absolute_change or 0.0,
            default=None,
        )
        complete_points = [
            (period, value)
            for index, (period, value) in enumerate(ordered)
            if index not in partial_indices
        ]
        if not complete_points:
            complete_points = list(ordered)
        start_period, start_value = complete_points[0]
        end_period, end_value = complete_points[-1]
        overall_change = end_value - start_value
        series_limitations = list(limitations)
        if len(points) < 3:
            series_limitations.append(
                "Fewer than three periods limit trend and anomaly interpretation."
            )
        if missing_periods:
            series_limitations.append(
                "Missing calendar periods were excluded from adjacent-period change calculations."
            )
        suspected_partial_periods = tuple(
            point.period for point in points if point.suspected_partial_period
        )
        if suspected_partial_periods:
            series_limitations.append(
                "Low-volume boundary periods were treated as potentially incomplete and excluded "
                "from changes and endpoints."
            )
        if any(points[index - 1].value == 0 for index in range(1, len(points))):
            series_limitations.append("Percent change is undefined after a zero-valued period.")
        return TimeSeriesAnalysis(
            dimension_column=dimension_column,
            metric_column=metric_column,
            start_period=self._period_label(start_period),
            end_period=self._period_label(end_period),
            start_value=start_value,
            end_value=end_value,
            absolute_change=overall_change,
            percent_change=None if start_value == 0 else overall_change / abs(start_value),
            largest_increase_period=(largest_increase.period if largest_increase else None),
            largest_increase=(largest_increase.absolute_change if largest_increase else None),
            largest_decrease_period=(largest_decrease.period if largest_decrease else None),
            largest_decrease=(largest_decrease.absolute_change if largest_decrease else None),
            anomaly_periods=tuple(point.period for point in points if point.is_anomaly),
            missing_periods=missing_periods,
            suspected_partial_periods=suspected_partial_periods,
            valid_comparison_count=len(comparison_changes),
            points=tuple(points),
            limitations=tuple(series_limitations),
        )

    @staticmethod
    def _parse_period(value: object) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _suspected_partial_indices(ordered: list[tuple[object, float]]) -> set[int]:
        if len(ordered) < 5:
            return set()
        typical_value = median(value for _, value in ordered)
        if typical_value <= 0:
            return set()
        threshold = typical_value * 0.1
        partial: set[int] = set()
        for index, (_, value) in enumerate(ordered):
            if value >= threshold:
                break
            partial.add(index)
        for index in range(len(ordered) - 1, -1, -1):
            if ordered[index][1] >= threshold:
                break
            partial.add(index)
        return partial

    @staticmethod
    def _is_consecutive_period(column_name: str, previous: object, current: object) -> bool:
        previous_date = DeterministicAnalysisEngine._parse_period(previous)
        current_date = DeterministicAnalysisEngine._parse_period(current)
        if previous_date is None or current_date is None:
            return False
        name = column_name.casefold()
        if "month" in name:
            expected_year = previous_date.year + (1 if previous_date.month == 12 else 0)
            expected_month = 1 if previous_date.month == 12 else previous_date.month + 1
            return (current_date.year, current_date.month) == (expected_year, expected_month)
        if "quarter" in name:
            month_difference = (current_date.year - previous_date.year) * 12
            month_difference += current_date.month - previous_date.month
            return month_difference == 3
        if "year" in name:
            return current_date.year == previous_date.year + 1
        if "week" in name:
            return (current_date.date() - previous_date.date()).days == 7
        return (current_date.date() - previous_date.date()).days == 1

    @staticmethod
    def _missing_months(
        column_name: str,
        ordered: list[tuple[object, float]],
    ) -> tuple[str, ...]:
        if "month" not in column_name.casefold():
            return ()
        missing: list[str] = []
        for index in range(1, len(ordered)):
            previous = DeterministicAnalysisEngine._parse_period(ordered[index - 1][0])
            current = DeterministicAnalysisEngine._parse_period(ordered[index][0])
            if previous is None or current is None:
                continue
            year = previous.year
            month = previous.month
            while True:
                month += 1
                if month == 13:
                    month = 1
                    year += 1
                if (year, month) >= (current.year, current.month):
                    break
                missing.append(f"{year:04d}-{month:02d}-01")
        return tuple(missing)

    @staticmethod
    def _period_sort_key(value: object) -> tuple[int, str]:
        parsed = DeterministicAnalysisEngine._parse_period(value)
        return (0, parsed.isoformat()) if parsed is not None else (1, str(value))

    @staticmethod
    def _period_label(value: object) -> str:
        return value.isoformat() if isinstance(value, (date, datetime)) else str(value)

    @staticmethod
    def _is_number(value: object) -> bool:
        return not isinstance(value, bool) and isinstance(value, (Real, Decimal))
