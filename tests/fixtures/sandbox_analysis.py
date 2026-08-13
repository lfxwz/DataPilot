import numpy as np


def analyze(data):
    values = np.asarray([row["value"] for row in data], dtype=float)
    return {
        "analysis_type": "sandbox_smoke_test",
        "summary_metrics": {"mean": float(values.mean())},
        "findings": ["The isolated sandbox computed the expected mean."],
        "diagnostics": {"row_count": int(values.size), "seed": 42},
        "limitations": ["This fixed program validates isolation, not model quality."],
    }
