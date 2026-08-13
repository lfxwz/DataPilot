"""Docker-backed execution boundary for admitted generated Python."""

import json
import subprocess
from collections.abc import Sequence
from hashlib import sha256
from time import perf_counter
from typing import Any

from pydantic import ValidationError

from datapilot.adapters.sandbox.errors import SandboxExecutionError
from datapilot.domain.generated_python import (
    GeneratedAnalysisOutput,
    GeneratedPythonAnalysis,
    GeneratedPythonProgram,
    PythonPolicyValidation,
    SandboxResourceLimits,
)

_RESULT_MARKER = "DATAPILOT_SANDBOX_RESULT="


class DockerSandboxExecutor:
    """Run each program as a fresh process in one persistent Python container."""

    def __init__(
        self,
        *,
        container_name: str,
        timeout_seconds: int = 45,
        memory_mb: int = 768,
        cpu_count: float = 1.0,
        docker_command: str = "docker",
    ) -> None:
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        if memory_mb < 128:
            raise ValueError("memory_mb must be at least 128")
        if cpu_count <= 0:
            raise ValueError("cpu_count must be positive")
        if not container_name.strip():
            raise ValueError("container_name must not be empty")
        self._container_name = container_name
        self._docker_command = docker_command
        self._limits = SandboxResourceLimits(
            timeout_seconds=timeout_seconds,
            memory_mb=memory_mb,
            cpu_count=cpu_count,
        )

    @property
    def resource_limits(self) -> SandboxResourceLimits:
        return self._limits

    def execute(
        self,
        *,
        program: GeneratedPythonProgram,
        policy: PythonPolicyValidation,
        records: Sequence[dict[str, Any]],
    ) -> GeneratedPythonAnalysis:
        actual_code_hash = sha256(program.code.encode("utf-8")).hexdigest()
        if not policy.accepted or policy.code_hash != actual_code_hash:
            raise SandboxExecutionError(
                "Generated Python does not match an accepted policy decision."
            )
        started = perf_counter()
        try:
            self._require_running_container()
            completed = self._run_command(
                [
                    self._docker_command,
                    "exec",
                    "--interactive",
                    self._container_name,
                    "python",
                    "/opt/datapilot/runner.py",
                ],
                stdin=json.dumps(
                    {"code": program.code, "data": records},
                    ensure_ascii=False,
                    default=str,
                ),
                timeout=self._limits.timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise SandboxExecutionError("Docker CLI is not available.") from exc
        except subprocess.TimeoutExpired as exc:
            raise SandboxExecutionError("Generated Python exceeded its time limit.") from exc
        duration_ms = (perf_counter() - started) * 1000

        if completed.returncode != 0:
            raise SandboxExecutionError(
                "Generated Python failed inside the isolated runner "
                f"(container exit code {completed.returncode})."
            )
        envelope = self._parse_envelope(completed.stdout)
        try:
            output = GeneratedAnalysisOutput.model_validate(envelope["output"])
        except (KeyError, TypeError, ValidationError) as exc:
            raise SandboxExecutionError(
                "Generated Python returned data outside the approved output contract."
            ) from exc

        stdout = envelope.get("stdout", "")
        if not isinstance(stdout, str):
            raise SandboxExecutionError("Generated Python returned an invalid stdout field.")
        return GeneratedPythonAnalysis(
            profile=program.profile,
            analysis_goal=program.analysis_goal,
            generated_code=program.code,
            policy=policy,
            output=output,
            duration_ms=duration_ms,
            stdout=stdout,
            resource_limits=self._limits,
            warnings=(
                "This result was produced by model-generated code and is experimental.",
                "The code ran in a fresh Python process inside the shared analysis container.",
            ),
        )

    def _require_running_container(self) -> None:
        completed = self._run_command(
            [
                self._docker_command,
                "inspect",
                "--format",
                "{{.State.Running}}",
                self._container_name,
            ],
            timeout=10,
        )
        if completed.returncode != 0 or completed.stdout.strip().casefold() != "true":
            detail = self._bounded_docker_error(completed)
            raise SandboxExecutionError(
                f"The shared Python container {self._container_name!r} is not running: {detail}"
            )

    @staticmethod
    def _bounded_docker_error(completed: subprocess.CompletedProcess[str]) -> str:
        message = completed.stderr.strip() or completed.stdout.strip()
        return " ".join(message.split())[:1000] or "Docker returned no diagnostic output."

    @staticmethod
    def _run_command(
        command: list[str],
        *,
        timeout: int,
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
        )

    @staticmethod
    def _parse_envelope(stdout: str) -> dict[str, Any]:
        marker_lines = [line for line in stdout.splitlines() if line.startswith(_RESULT_MARKER)]
        if len(marker_lines) != 1:
            raise SandboxExecutionError("Sandbox did not return exactly one result envelope.")
        try:
            value = json.loads(marker_lines[0][len(_RESULT_MARKER) :])
        except json.JSONDecodeError as exc:
            raise SandboxExecutionError("Sandbox returned malformed JSON.") from exc
        if not isinstance(value, dict):
            raise SandboxExecutionError("Sandbox result envelope must be a JSON object.")
        return value
