"""LangGraph orchestration for one bounded, auditable analysis run."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.exc import SQLAlchemyError

from datapilot.adapters.database import PostgresAnalyticsDatabase
from datapilot.adapters.database.errors import QueryPolicyError
from datapilot.domain.agent import (
    AnalysisNarrative,
    DeterministicAnalysis,
    QueryResultProfile,
)
from datapilot.domain.analysis import AnalysisPlan, AnalysisRequest
from datapilot.domain.generated_python import GeneratedPythonAnalysis
from datapilot.domain.query import QueryExecutionResult
from datapilot.domain.schema import SchemaSnapshot
from datapilot.domain.sql import SQLCandidate, SQLValidationResult
from datapilot.policies.sql_safety import SQLSafetyPolicy
from datapilot.services.deterministic_analysis import DeterministicAnalysisEngine
from datapilot.services.generated_python import GeneratedPythonAnalyzer
from datapilot.services.planning import AnalysisPlanner
from datapilot.services.result_profiling import QueryResultProfiler
from datapilot.services.sql_generation import SQLGenerator
from datapilot.services.synthesis import AnalysisSynthesizer


class AnalysisAgentState(TypedDict, total=False):
    request: AnalysisRequest
    schema: SchemaSnapshot
    plan: AnalysisPlan
    sql_candidate: SQLCandidate
    sql_validation: SQLValidationResult
    query_result: QueryExecutionResult
    python_profile: QueryResultProfile
    deterministic_analyses: tuple[DeterministicAnalysis, ...]
    generated_python_analysis: GeneratedPythonAnalysis | None
    narrative: AnalysisNarrative
    sql_retry_count: int


def build_analysis_agent_graph(
    *,
    database: PostgresAnalyticsDatabase,
    planner: AnalysisPlanner,
    sql_generator: SQLGenerator,
    policy: SQLSafetyPolicy,
    profiler: QueryResultProfiler,
    deterministic_engine: DeterministicAnalysisEngine,
    generated_python_analyzer: GeneratedPythonAnalyzer,
    synthesizer: AnalysisSynthesizer,
    schema_names: tuple[str, ...],
    max_sql_retries: int = 2,
) -> CompiledStateGraph[
    AnalysisAgentState,
    None,
    AnalysisAgentState,
    AnalysisAgentState,
]:
    """Compile the sequential safety pipeline with explicit typed boundaries."""

    def inspect_schema(state: AnalysisAgentState) -> AnalysisAgentState:
        return {"schema": database.inspect_schema(schema_names)}

    def create_plan(state: AnalysisAgentState) -> AnalysisAgentState:
        return {"plan": planner.create_plan(state["request"], state["schema"])}

    def generate_sql(state: AnalysisAgentState) -> AnalysisAgentState:
        return {
            "sql_candidate": sql_generator.generate(
                state["request"],
                state["plan"],
                state["schema"],
            )
        }

    def execute_sql(state: AnalysisAgentState) -> AnalysisAgentState:
        candidate = state["sql_candidate"]
        retry_count = 0
        while True:
            validation = policy.validate(candidate)
            if not validation.accepted or validation.normalized_sql is None:
                issues = ", ".join(issue.code for issue in validation.issues)
                raise QueryPolicyError(f"Agent SQL was rejected by policy: {issues}")
            try:
                query_result = database.execute(candidate)
            except SQLAlchemyError as exc:
                if retry_count >= max_sql_retries:
                    raise
                retry_count += 1
                candidate = sql_generator.repair(
                    state["request"],
                    state["plan"],
                    state["schema"],
                    failed_candidate=candidate,
                    database_error=_database_error_feedback(exc),
                    attempt=retry_count,
                )
                continue
            return {
                "sql_candidate": candidate,
                "sql_validation": validation,
                "query_result": query_result,
                "sql_retry_count": retry_count,
            }

    def profile_result(state: AnalysisAgentState) -> AnalysisAgentState:
        return {"python_profile": profiler.profile(state["query_result"])}

    def run_deterministic_analysis(state: AnalysisAgentState) -> AnalysisAgentState:
        return {"deterministic_analyses": deterministic_engine.analyze(state["query_result"])}

    def run_generated_python(state: AnalysisAgentState) -> AnalysisAgentState:
        analysis = generated_python_analyzer.analyze_if_needed(
            request=state["request"],
            plan=state["plan"],
            result=state["query_result"],
            profile=state["python_profile"],
        )
        return {"generated_python_analysis": analysis}

    def synthesize(state: AnalysisAgentState) -> AnalysisAgentState:
        return {
            "narrative": synthesizer.synthesize(
                request=state["request"],
                plan=state["plan"],
                normalized_sql=state["sql_validation"].normalized_sql or "",
                result=state["query_result"],
                profile=state["python_profile"],
                deterministic_analyses=state["deterministic_analyses"],
                generated_python_analysis=state.get("generated_python_analysis"),
            )
        }

    builder = StateGraph(AnalysisAgentState)
    builder.add_node("inspect_schema", inspect_schema)
    builder.add_node("create_plan", create_plan)
    builder.add_node("generate_sql", generate_sql)
    builder.add_node("execute_sql", execute_sql)
    builder.add_node("profile_result", profile_result)
    builder.add_node("run_deterministic_analysis", run_deterministic_analysis)
    builder.add_node("run_generated_python", run_generated_python)
    builder.add_node("synthesize", synthesize)
    builder.add_edge(START, "inspect_schema")
    builder.add_edge("inspect_schema", "create_plan")
    builder.add_edge("create_plan", "generate_sql")
    builder.add_edge("generate_sql", "execute_sql")
    builder.add_edge("execute_sql", "profile_result")
    builder.add_edge("profile_result", "run_deterministic_analysis")
    builder.add_edge("run_deterministic_analysis", "run_generated_python")
    builder.add_edge("run_generated_python", "synthesize")
    builder.add_edge("synthesize", END)
    return builder.compile()


def _database_error_feedback(exc: SQLAlchemyError) -> str:
    """Return bounded driver feedback without connection details or a traceback."""

    driver_error = getattr(exc, "orig", None)
    source = driver_error if driver_error is not None else exc
    message = " ".join(str(source).split())
    return f"{type(source).__name__}: {message}"[:4000]
