"""Adversarial tests for model-generated Python admission policy."""

import pytest

from datapilot.domain.generated_python import SandboxProfile
from datapilot.policies.python_safety import PythonSafetyPolicy


def test_policy_accepts_bounded_numeric_analysis() -> None:
    code = """import numpy as np

SEED = 42

def analyze(data):
    values = np.asarray([row["value"] for row in data], dtype=float)
    return {
        "analysis_type": "mean",
        "summary_metrics": {"mean": float(values.mean())},
        "findings": ["Computed the observed mean."],
        "diagnostics": {"row_count": int(values.size), "seed": SEED},
        "limitations": ["This is descriptive."],
    }
"""

    result = PythonSafetyPolicy().validate(code, SandboxProfile.ANALYTICS)

    assert result.accepted is True
    assert result.issues == ()


@pytest.mark.parametrize(
    ("attack", "issue_code"),
    [
        ("def analyze(data):\n    return open('/etc/passwd').read()", "call_not_allowed"),
        ("import subprocess\ndef analyze(data):\n    return {}", "import_not_allowed"),
        ("def analyze(data):\n    return __import__('os')", "call_not_allowed"),
        ("print('top level')\ndef analyze(data):\n    return {}", "top_level_execution"),
        ("x = list()\ndef analyze(data):\n    return {}", "non_constant_top_level_assignment"),
        (
            "import pandas as pd\ndef analyze(data):\n    return pd.read_csv('/etc/passwd')",
            "call_not_allowed",
        ),
        (
            "import numpy as np\ndef analyze(data):\n    return np.load('/etc/passwd')",
            "call_not_allowed",
        ),
        ("def analyze(data):\n    return data.__class__", "dunder_access"),
    ],
)
def test_policy_rejects_common_escape_and_io_attempts(attack: str, issue_code: str) -> None:
    result = PythonSafetyPolicy().validate(attack, SandboxProfile.ANALYTICS)

    assert result.accepted is False
    assert issue_code in {issue.code for issue in result.issues}


def test_unified_environment_allows_torch_in_every_profile() -> None:
    code = """import torch

def analyze(data):
    model = torch.nn.Linear(1, 1)
    model.eval()
    return {"x": torch.tensor([1]).item()}
"""

    analytics = PythonSafetyPolicy().validate(code, SandboxProfile.ANALYTICS)
    deep_learning = PythonSafetyPolicy().validate(code, SandboxProfile.DEEP_LEARNING)

    assert analytics.accepted is True
    assert deep_learning.accepted is True


def test_builtin_eval_is_rejected_but_pytorch_model_eval_is_allowed() -> None:
    builtin = PythonSafetyPolicy().validate(
        "def analyze(data):\n    return eval('1 + 1')",
        SandboxProfile.DEEP_LEARNING,
    )
    method = PythonSafetyPolicy().validate(
        """import torch

def analyze(data):
    model = torch.nn.Linear(1, 1)
    model.eval()
    return {"ok": True}
""",
        SandboxProfile.DEEP_LEARNING,
    )

    assert builtin.accepted is False
    assert method.accepted is True
