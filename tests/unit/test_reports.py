"""Validation tests for generated charts and trusted Markdown reports."""

import pytest
from pydantic import ValidationError

from datapilot.domain.generated_python import ChartSeries, GeneratedAnalysisOutput


def test_chart_series_requires_matching_axes() -> None:
    with pytest.raises(ValidationError, match="lengths must match"):
        ChartSeries(name="orders", x=("delivered", "shipped"), y=(10.0,))


def test_generated_output_accepts_bounded_chart_and_report() -> None:
    output = GeneratedAnalysisOutput.model_validate(
        {
            "analysis_type": "distribution",
            "summary_metrics": {"total": 12},
            "findings": ["Delivered dominates."],
            "diagnostics": {"row_count": 2},
            "limitations": ["Descriptive only."],
            "visualizations": [
                {
                    "chart_id": "order_status",
                    "chart_type": "bar",
                    "title": "Orders by status",
                    "description": "Observed counts by status.",
                    "x_label": "Status",
                    "y_label": "Orders",
                    "series": [{"name": "orders", "x": ["delivered", "shipped"], "y": [10, 2]}],
                }
            ],
            "report_markdown": "# Report\n\nDelivered dominates the observed rows.",
        }
    )

    assert output.visualizations[0].series[0].y == (10.0, 2.0)
    assert output.report_markdown is not None


@pytest.mark.parametrize("payload", ["<script>alert(1)</script>", "![x](data:image/png,x)"])
def test_report_markdown_rejects_embedded_or_executable_content(payload: str) -> None:
    with pytest.raises(ValidationError, match="forbidden"):
        GeneratedAnalysisOutput(
            analysis_type="unsafe_report",
            findings=("Unsafe report rejected.",),
            limitations=("None.",),
            report_markdown=payload,
        )
