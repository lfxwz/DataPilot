"""Safe deterministic profiling for bounded SQL result sets."""

from __future__ import annotations

from collections.abc import Hashable
from decimal import Decimal
from math import isfinite
from numbers import Real
from typing import cast

from datapilot.domain.agent import ColumnProfile, NumericSummary, QueryResultProfile
from datapilot.domain.query import QueryExecutionResult


class QueryResultProfiler:
    """Compute compact descriptive evidence without executing generated Python."""

    def __init__(self, *, sample_values: int = 5) -> None:
        if sample_values < 1:
            raise ValueError("sample_values must be positive")
        self._sample_values = sample_values

    def profile(self, result: QueryExecutionResult) -> QueryResultProfile:
        columns = tuple(
            self._profile_column(
                name,
                tuple(row[index] for row in result.rows),
            )
            for index, name in enumerate(result.columns)
        )
        return QueryResultProfile(
            row_count=result.row_count,
            truncated=result.truncated,
            columns=columns,
        )

    def _profile_column(self, name: str, values: tuple[object, ...]) -> ColumnProfile:
        non_null = tuple(value for value in values if value is not None)
        numeric_values = tuple(
            float(cast(Real | Decimal, value))
            for value in non_null
            if self._is_finite_number(value)
        )
        numeric = None
        if numeric_values and len(numeric_values) == len(non_null):
            numeric = NumericSummary(
                minimum=min(numeric_values),
                maximum=max(numeric_values),
                mean=sum(numeric_values) / len(numeric_values),
                total=sum(numeric_values),
            )

        distinct_values = {value for value in non_null if isinstance(value, Hashable)}
        samples = tuple(dict.fromkeys(str(value) for value in non_null))[: self._sample_values]
        return ColumnProfile(
            name=name,
            non_null_count=len(non_null),
            null_count=len(values) - len(non_null),
            distinct_count=len(distinct_values),
            numeric=numeric,
            sample_values=samples,
        )

    @staticmethod
    def _is_finite_number(value: object) -> bool:
        if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
            return False
        return isfinite(float(value))
