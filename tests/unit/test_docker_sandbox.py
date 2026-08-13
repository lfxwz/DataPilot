"""Unit tests for Docker sandbox protocol validation and result handling."""

import json
import subprocess

import pytest

from datapilot.adapters.sandbox import DockerSandboxExecutor, SandboxExecutionError
from datapilot.domain.generated_python import GeneratedPythonProgram, SandboxProfile
from datapilot.policies.python_safety import PythonSafetyPolicy


def _program() -> GeneratedPythonProgram:
    return GeneratedPythonProgram(
        analysis_goal="Compute a bounded mean",
        profile=SandboxProfile.ANALYTICS,
        code=(
            "def analyze(data):\n"
            "    return {'analysis_type': 'mean', 'summary_metrics': {'mean': 1.5}, "
            "'findings': ['ok'], 'diagnostics': {}, 'limitations': ['bounded']}"
        ),
        expected_outputs=("mean",),
    )


def test_executor_validates_protocol_and_builds_experimental_result(monkeypatch) -> None:
    executor = DockerSandboxExecutor(
        container_name="datapilot-python-runtime",
        timeout_seconds=12,
        memory_mb=256,
        cpu_count=0.5,
    )
    program = _program()
    policy = PythonSafetyPolicy().validate(program.code, program.profile)
    envelope = {
        "output": {
            "analysis_type": "mean",
            "summary_metrics": {"mean": 1.5},
            "findings": ["Computed the mean."],
            "diagnostics": {"row_count": 2},
            "limitations": ["Bounded sample."],
        },
        "stdout": "",
    }
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[1] == "inspect":
            return subprocess.CompletedProcess(command, 0, "true\n", "")
        return subprocess.CompletedProcess(
            command,
            0,
            "DATAPILOT_SANDBOX_RESULT=" + json.dumps(envelope),
            "",
        )

    monkeypatch.setattr(executor, "_run_command", run)

    result = executor.execute(
        program=program,
        policy=policy,
        records=({"value": 1}, {"value": 2}),
    )

    assert result.classification == "experimental_generated_code"
    assert result.output.summary_metrics["mean"] == 1.5
    assert result.resource_limits.network_disabled is True
    assert calls[0][1:3] == ["inspect", "--format"]
    assert calls[1][1:4] == ["exec", "--interactive", "datapilot-python-runtime"]


def test_executor_rejects_unadmitted_code() -> None:
    program = _program()
    policy = PythonSafetyPolicy().validate(program.code, program.profile)
    wrong_program = program.model_copy(update={"code": program.code + "\n# changed"})
    executor = DockerSandboxExecutor(container_name="datapilot-python-runtime")

    with pytest.raises(SandboxExecutionError, match="accepted policy"):
        executor.execute(program=wrong_program, policy=policy, records=())


def test_executor_reports_stopped_shared_container(monkeypatch) -> None:
    executor = DockerSandboxExecutor(container_name="datapilot-python-runtime")
    monkeypatch.setattr(
        executor,
        "_run_command",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 1, "", "No such container: datapilot-python-runtime"
        ),
    )

    with pytest.raises(SandboxExecutionError, match=r"is not running.*No such container"):
        executor._require_running_container()


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "DATAPILOT_SANDBOX_RESULT=not-json",
        "DATAPILOT_SANDBOX_RESULT=[]",
        "DATAPILOT_SANDBOX_RESULT={}\nDATAPILOT_SANDBOX_RESULT={}",
    ],
)
def test_result_envelope_rejects_malformed_protocol(stdout: str) -> None:
    with pytest.raises(SandboxExecutionError):
        DockerSandboxExecutor._parse_envelope(stdout)
