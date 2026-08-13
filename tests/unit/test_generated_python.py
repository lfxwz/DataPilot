"""Tests for conditional DeepSeek-generated Python analysis orchestration."""

from typing import Any

from datapilot.domain.agent import QueryResultProfile
from datapilot.domain.analysis import (
    AnalysisPlan,
    AnalysisRequest,
    AnalysisStep,
    PythonExecutionMode,
    StepType,
)
from datapilot.domain.generated_python import (
    GeneratedAnalysisOutput,
    GeneratedPythonAnalysis,
    GeneratedPythonProgram,
    PythonPolicyValidation,
    SandboxResourceLimits,
)
from datapilot.domain.llm import LLMUsage, StructuredCompletion
from datapilot.domain.query import QueryExecutionResult, QueryPlanSummary
from datapilot.policies.python_safety import PythonSafetyPolicy
from datapilot.services.generated_python import GeneratedPythonAnalyzer


class FakeCodeLLM:
    calls = 0

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
    ) -> StructuredCompletion:
        self.calls += 1
        assert "analyze(data)" in system_prompt
        assert max_tokens == 8000
        code = """import numpy as np

def analyze(data):
    values = np.asarray([row["feature"] for row in data], dtype=float)
    return {
        "analysis_type": "custom_numeric",
        "summary_metrics": {"mean": float(values.mean())},
        "findings": ["Computed a custom numeric result."],
        "diagnostics": {"row_count": int(values.size), "seed": 42},
        "limitations": ["Exploratory generated-code analysis."],
    }
"""
        return StructuredCompletion(
            model="test",
            usage=LLMUsage(),
            data={
                "analysis_goal": "Run custom numeric analysis",
                "profile": "analytics",
                "code": code,
                "expected_outputs": ["mean"],
                "assumptions": [],
            },
        )


class RecordingExecutor:
    called = False

    def execute(
        self,
        *,
        program: GeneratedPythonProgram,
        policy: PythonPolicyValidation,
        records: tuple[dict[str, Any], ...],
    ) -> GeneratedPythonAnalysis:
        self.called = True
        assert records == ({"feature": 1.0}, {"feature": 2.0})
        return GeneratedPythonAnalysis(
            profile=program.profile,
            analysis_goal=program.analysis_goal,
            generated_code=program.code,
            policy=policy,
            output=GeneratedAnalysisOutput(
                analysis_type="custom_numeric",
                summary_metrics={"mean": 1.5},
                findings=("Computed a custom numeric result.",),
                diagnostics={"row_count": 2, "seed": 42, "hidden_layers": [16, 8]},
                limitations=("Exploratory generated-code analysis.",),
            ),
            duration_ms=5,
            resource_limits=SandboxResourceLimits(
                timeout_seconds=45,
                memory_mb=768,
                cpu_count=1,
            ),
        )


def _result() -> QueryExecutionResult:
    return QueryExecutionResult(
        query_hash="d" * 64,
        columns=("feature",),
        rows=((1.0,), (2.0,)),
        row_count=2,
        truncated=False,
        duration_ms=1,
        plan=QueryPlanSummary(node_type="Result", estimated_cost=1, estimated_rows=2),
    )


def test_custom_plan_generates_and_executes_admitted_code() -> None:
    llm = FakeCodeLLM()
    executor = RecordingExecutor()
    analyzer = GeneratedPythonAnalyzer(llm, policy=PythonSafetyPolicy(), executor=executor)
    plan = AnalysisPlan(
        objective="Run custom numeric analysis",
        steps=(
            AnalysisStep(
                id="custom_analysis",
                type=StepType.PYTHON_ANALYSIS,
                description="Run unsupported custom numeric analysis",
                python_mode=PythonExecutionMode.GENERATED_ANALYTICS,
            ),
        ),
    )

    output = analyzer.analyze_if_needed(
        request=AnalysisRequest(question="Run a custom numeric analysis"),
        plan=plan,
        result=_result(),
        profile=QueryResultProfile(row_count=2, truncated=False, columns=()),
    )

    assert output is not None
    assert output.output.summary_metrics["mean"] == 1.5
    assert llm.calls == 1
    assert executor.called is True


def test_verified_plan_never_calls_code_generator() -> None:
    llm = FakeCodeLLM()
    executor = RecordingExecutor()
    analyzer = GeneratedPythonAnalyzer(llm, policy=PythonSafetyPolicy(), executor=executor)
    plan = AnalysisPlan(
        objective="Describe a distribution",
        steps=(
            AnalysisStep(
                id="distribution",
                type=StepType.PYTHON_ANALYSIS,
                description="Compute verified distribution",
                python_mode=PythonExecutionMode.VERIFIED,
            ),
        ),
    )

    output = analyzer.analyze_if_needed(
        request=AnalysisRequest(
            question="Describe the distribution",
            include_visualizations=False,
            include_report=False,
        ),
        plan=plan,
        result=_result(),
        profile=QueryResultProfile(row_count=2, truncated=False, columns=()),
    )

    assert output is None
    assert llm.calls == 0
    assert executor.called is False


class RepairingCodeLLM(FakeCodeLLM):
    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
    ) -> StructuredCompletion:
        if self.calls == 0:
            self.calls += 1
            assert "policy_rejection_feedback" not in user_prompt
            return StructuredCompletion(
                model="test",
                usage=LLMUsage(),
                data={
                    "analysis_goal": "Run custom numeric analysis",
                    "profile": "analytics",
                    "code": "def analyze(data):\n    return open('/tmp/result').read()",
                    "expected_outputs": ["mean"],
                    "assumptions": [],
                },
            )
        assert "call_not_allowed" in user_prompt
        return super().complete_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
        )


def test_rejected_program_is_repaired_before_execution() -> None:
    llm = RepairingCodeLLM()
    executor = RecordingExecutor()
    analyzer = GeneratedPythonAnalyzer(llm, policy=PythonSafetyPolicy(), executor=executor)
    plan = AnalysisPlan(
        objective="Run custom numeric analysis",
        steps=(
            AnalysisStep(
                id="custom_analysis",
                type=StepType.PYTHON_ANALYSIS,
                description="Run unsupported custom numeric analysis",
                python_mode=PythonExecutionMode.GENERATED_ANALYTICS,
            ),
        ),
    )

    output = analyzer.analyze_if_needed(
        request=AnalysisRequest(question="Run a custom numeric analysis"),
        plan=plan,
        result=_result(),
        profile=QueryResultProfile(row_count=2, truncated=False, columns=()),
    )

    assert output is not None
    assert llm.calls == 2
    assert executor.called is True
