"""LLM code generation, static admission, and isolated execution orchestration."""

import json
from typing import Any, Protocol

from pydantic import ValidationError

from datapilot.adapters.llm.errors import LLMResponseValidationError
from datapilot.adapters.sandbox.errors import GeneratedCodePolicyError, SandboxExecutionError
from datapilot.domain.agent import QueryResultProfile
from datapilot.domain.analysis import (
    AnalysisPlan,
    AnalysisRequest,
    PythonExecutionMode,
    StepType,
)
from datapilot.domain.generated_python import (
    GeneratedPythonAnalysis,
    GeneratedPythonProgram,
    PythonPolicyValidation,
    SandboxProfile,
)
from datapilot.domain.query import QueryExecutionResult
from datapilot.policies.python_safety import PythonSafetyPolicy
from datapilot.prompts.python_generator import SYSTEM_PROMPT
from datapilot.services.planning import StructuredLLM


class GeneratedCodeExecutor(Protocol):
    def execute(
        self,
        *,
        program: GeneratedPythonProgram,
        policy: PythonPolicyValidation,
        records: tuple[dict[str, Any], ...],
    ) -> GeneratedPythonAnalysis: ...


class GeneratedPythonAnalyzer:
    """Generate code only for plan steps outside the verified function registry."""

    def __init__(
        self,
        llm: StructuredLLM,
        *,
        policy: PythonSafetyPolicy,
        executor: GeneratedCodeExecutor | None,
        max_policy_retries: int = 2,
    ) -> None:
        if max_policy_retries < 0:
            raise ValueError("max_policy_retries must not be negative")
        self._llm = llm
        self._policy = policy
        self._executor = executor
        self._max_policy_retries = max_policy_retries

    def analyze_if_needed(
        self,
        *,
        request: AnalysisRequest,
        plan: AnalysisPlan,
        result: QueryExecutionResult,
        profile: QueryResultProfile,
    ) -> GeneratedPythonAnalysis | None:
        sandbox_profile = self._requested_profile(plan, request)
        if sandbox_profile is None or not request.allow_generated_python:
            return None
        if self._executor is None:
            if self._has_explicit_generated_step(plan):
                raise SandboxExecutionError(
                    "Generated Python execution is disabled by the operator."
                )
            return None

        policy_feedback: tuple[dict[str, str | int | None], ...] = ()
        for attempt in range(self._max_policy_retries + 1):
            program = self._generate(
                request=request,
                plan=plan,
                result=result,
                profile=profile,
                required_profile=sandbox_profile,
                policy_feedback=policy_feedback,
            )
            validation = self._policy.validate(program.code, program.profile)
            if validation.accepted:
                break
            policy_feedback = tuple(
                {
                    "code": issue.code,
                    "message": issue.message,
                    "line": issue.line,
                }
                for issue in validation.issues
            )
            if attempt == self._max_policy_retries:
                issue_codes = ", ".join(issue.code for issue in validation.issues)
                raise GeneratedCodePolicyError(
                    f"Generated Python was rejected by policy: {issue_codes}"
                )
        else:
            raise AssertionError("unreachable")
        records = tuple(dict(zip(result.columns, row, strict=True)) for row in result.rows)
        return self._executor.execute(program=program, policy=validation, records=records)

    def _generate(
        self,
        *,
        request: AnalysisRequest,
        plan: AnalysisPlan,
        result: QueryExecutionResult,
        profile: QueryResultProfile,
        required_profile: SandboxProfile,
        policy_feedback: tuple[dict[str, str | int | None], ...],
    ) -> GeneratedPythonProgram:
        allowed_imports = [
            "collections",
            "datetime",
            "decimal",
            "functools",
            "itertools",
            "json",
            "lightgbm",
            "math",
            "networkx",
            "numpy",
            "openpyxl",
            "pandas",
            "polars",
            "plotly",
            "matplotlib",
            "pyarrow",
            "seaborn",
            "scipy",
            "sklearn",
            "statistics",
            "statsmodels",
            "sympy",
            "torch",
            "xgboost",
        ]
        payload = {
            "question": request.question,
            "analysis_plan": plan.model_dump(mode="json"),
            "required_profile": required_profile,
            "allowed_imports": allowed_imports,
            "query_metadata": {
                "columns": result.columns,
                "row_count": result.row_count,
                "truncated": result.truncated,
            },
            "deliverables": {
                "include_visualizations": request.include_visualizations,
                "include_report": request.include_report,
                "maximum_charts": 4,
                "maximum_points_per_series": 500,
            },
            "python_profile": profile.model_dump(mode="json"),
            "sample_records": [
                dict(zip(result.columns, row, strict=True)) for row in result.rows[:10]
            ],
            "output_json_schema": GeneratedPythonProgram.model_json_schema(),
        }
        if policy_feedback:
            payload["policy_rejection_feedback"] = policy_feedback
            payload["repair_instruction"] = (
                "Generate a new complete program that removes every rejected operation. "
                "Do not explain or preserve the rejected code."
            )
        completion = self._llm.complete_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=json.dumps(payload, ensure_ascii=False, default=str),
            max_tokens=8000,
        )
        try:
            program = GeneratedPythonProgram.model_validate(completion.data)
        except ValidationError as exc:
            raise LLMResponseValidationError(
                "Generated Python did not satisfy the program contract."
            ) from exc
        if program.profile is not required_profile:
            raise LLMResponseValidationError(
                "Generated Python selected a sandbox profile different from the approved plan."
            )
        return program

    @staticmethod
    def _requested_profile(
        plan: AnalysisPlan,
        request: AnalysisRequest,
    ) -> SandboxProfile | None:
        generated_modes = {
            step.python_mode
            for step in plan.steps
            if step.type is StepType.PYTHON_ANALYSIS
            and step.python_mode
            in {
                PythonExecutionMode.GENERATED_ANALYTICS,
                PythonExecutionMode.GENERATED_DEEP_LEARNING,
            }
        }
        if PythonExecutionMode.GENERATED_DEEP_LEARNING in generated_modes:
            return SandboxProfile.DEEP_LEARNING
        if PythonExecutionMode.GENERATED_ANALYTICS in generated_modes:
            return SandboxProfile.ANALYTICS
        if request.include_visualizations or request.include_report:
            return SandboxProfile.ANALYTICS
        return None

    @staticmethod
    def _has_explicit_generated_step(plan: AnalysisPlan) -> bool:
        return any(
            step.type is StepType.PYTHON_ANALYSIS
            and step.python_mode
            in {
                PythonExecutionMode.GENERATED_ANALYTICS,
                PythonExecutionMode.GENERATED_DEEP_LEARNING,
            }
            for step in plan.steps
        )
