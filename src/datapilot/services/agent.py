"""Application service for the complete analysis-agent workflow."""

from time import perf_counter
from uuid import uuid4

from datapilot.adapters.database import PostgresAnalyticsDatabase
from datapilot.adapters.database.run_repository import PostgresAnalysisRunRepository
from datapilot.domain.agent import AgentAnalysisResult
from datapilot.domain.analysis import AnalysisRequest
from datapilot.domain.common import ErrorInfo, RunStatus, utc_now
from datapilot.policies.python_safety import PythonSafetyPolicy
from datapilot.policies.sql_safety import SQLSafetyPolicy
from datapilot.prompts.analysis_planner import PLANNER_PROMPT_VERSION
from datapilot.prompts.python_generator import PYTHON_GENERATOR_PROMPT_VERSION
from datapilot.prompts.sql_generator import SQL_GENERATOR_PROMPT_VERSION
from datapilot.prompts.synthesis import SYNTHESIS_PROMPT_VERSION
from datapilot.services.deterministic_analysis import DeterministicAnalysisEngine
from datapilot.services.generated_python import GeneratedCodeExecutor, GeneratedPythonAnalyzer
from datapilot.services.planning import AnalysisPlanner, StructuredLLM
from datapilot.services.result_profiling import QueryResultProfiler
from datapilot.services.sql_generation import SQLGenerator
from datapilot.services.synthesis import AnalysisSynthesizer
from datapilot.workflows.analysis_agent_graph import build_analysis_agent_graph


class AnalysisAgent:
    """Execute a question through typed LLM and deterministic database boundaries."""

    def __init__(
        self,
        *,
        database: PostgresAnalyticsDatabase,
        llm: StructuredLLM,
        policy: SQLSafetyPolicy,
        model_name: str,
        schema_names: tuple[str, ...],
        max_sql_retries: int = 2,
        generated_code_executor: GeneratedCodeExecutor | None = None,
        run_repository: PostgresAnalysisRunRepository | None = None,
    ) -> None:
        self._model_name = model_name
        self._run_repository = run_repository
        self._graph = build_analysis_agent_graph(
            database=database,
            planner=AnalysisPlanner(llm),
            sql_generator=SQLGenerator(llm),
            policy=policy,
            profiler=QueryResultProfiler(),
            deterministic_engine=DeterministicAnalysisEngine(),
            generated_python_analyzer=GeneratedPythonAnalyzer(
                llm,
                policy=PythonSafetyPolicy(),
                executor=generated_code_executor,
            ),
            synthesizer=AnalysisSynthesizer(llm),
            schema_names=schema_names,
            max_sql_retries=max_sql_retries,
        )

    def analyze(self, request: AnalysisRequest) -> AgentAnalysisResult:
        run_id = uuid4()
        started_at = utc_now()
        started_clock = perf_counter()
        if self._run_repository is not None:
            self._run_repository.start_run(
                run_id=run_id,
                question=request.question,
                session_id=request.session_id,
                model_name=self._model_name,
                started_at=started_at,
            )
        try:
            state = self._graph.invoke({"request": request})
        except Exception as exc:
            if self._run_repository is not None:
                self._run_repository.fail_run(
                    run_id=run_id,
                    status=self._failure_status(exc),
                    completed_at=utc_now(),
                    duration_ms=(perf_counter() - started_clock) * 1000,
                    error=self._safe_error(exc),
                )
            raise
        completed_at = utc_now()

        prompt_versions = [
            PLANNER_PROMPT_VERSION,
            SQL_GENERATOR_PROMPT_VERSION,
            SYNTHESIS_PROMPT_VERSION,
        ]
        if state.get("generated_python_analysis") is not None:
            prompt_versions.insert(2, PYTHON_GENERATOR_PROMPT_VERSION)

        result = AgentAnalysisResult(
            run_id=run_id,
            status=RunStatus.SUCCEEDED,
            question=request.question,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=(perf_counter() - started_clock) * 1000,
            model_name=self._model_name,
            prompt_versions=tuple(prompt_versions),
            schema_tables=tuple(table.qualified_name for table in state["schema"].tables),
            plan=state["plan"],
            sql_candidate=state["sql_candidate"],
            sql_validation=state["sql_validation"],
            sql_retry_count=state.get("sql_retry_count", 0),
            query_result=state["query_result"],
            python_profile=state["python_profile"],
            deterministic_analyses=state["deterministic_analyses"],
            generated_python_analysis=state.get("generated_python_analysis"),
            narrative=state["narrative"],
        )
        if self._run_repository is not None:
            self._run_repository.complete_run(result)
        return result

    @staticmethod
    def _failure_status(exc: Exception) -> RunStatus:
        from datapilot.adapters.database.errors import QueryPolicyError
        from datapilot.adapters.llm.errors import LLMResponseValidationError
        from datapilot.adapters.sandbox.errors import GeneratedCodePolicyError

        rejected_errors = (QueryPolicyError, LLMResponseValidationError, GeneratedCodePolicyError)
        return RunStatus.REJECTED if isinstance(exc, rejected_errors) else RunStatus.FAILED

    @staticmethod
    def _safe_error(exc: Exception) -> ErrorInfo:
        from datapilot.adapters.database.errors import (
            QueryBudgetExceededError,
            QueryPolicyError,
            ReadOnlyBoundaryError,
        )
        from datapilot.adapters.llm.errors import LLMProviderError, LLMResponseValidationError
        from datapilot.adapters.sandbox.errors import (
            GeneratedCodePolicyError,
            SandboxExecutionError,
        )

        error_types: tuple[tuple[type[Exception], str, str, bool], ...] = (
            (GeneratedCodePolicyError, "generated_code_rejected", str(exc), False),
            (LLMResponseValidationError, "llm_response_invalid", str(exc), True),
            (QueryPolicyError, "sql_policy_rejected", str(exc), False),
            (
                QueryBudgetExceededError,
                "query_budget_exceeded",
                "The query exceeded its configured execution budget.",
                False,
            ),
            (
                SandboxExecutionError,
                "sandbox_execution_failed",
                "Generated analysis failed inside the isolated runner.",
                False,
            ),
            (
                LLMProviderError,
                "llm_provider_unavailable",
                "The configured analysis model is temporarily unavailable.",
                True,
            ),
            (
                ReadOnlyBoundaryError,
                "read_only_boundary_failed",
                "The database read-only boundary could not be confirmed.",
                False,
            ),
        )
        for error_type, code, message, retryable in error_types:
            if isinstance(exc, error_type):
                return ErrorInfo(code=code, message=message, retryable=retryable)
        return ErrorInfo(
            code="analysis_failed",
            message="The analysis failed unexpectedly.",
            retryable=False,
        )
