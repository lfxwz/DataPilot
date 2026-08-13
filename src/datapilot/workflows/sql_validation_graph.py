"""First executable LangGraph slice: deterministic SQL policy validation."""

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from datapilot.domain.common import ErrorInfo, RunStatus
from datapilot.policies.sql_safety import SQLSafetyPolicy
from datapilot.workflows.state import RunState


def build_sql_validation_graph(
    policy: SQLSafetyPolicy,
) -> CompiledStateGraph[RunState, None, RunState, RunState]:
    """Compile a small graph that validates one SQL candidate.

    The graph deliberately performs no database I/O. Later milestones will add
    EXPLAIN, execution, result validation, and bounded repair as separate nodes.
    """

    def validate_sql(state: RunState) -> RunState:
        candidate = state.get("sql_candidate")
        if candidate is None:
            return {
                "status": RunStatus.FAILED,
                "error": ErrorInfo(
                    code="missing_sql_candidate",
                    message="The workflow requires a SQL candidate.",
                    retryable=False,
                ),
            }

        result = policy.validate(candidate)
        if result.accepted:
            return {
                "sql_validation": result,
                "status": RunStatus.SUCCEEDED,
                "error": None,
            }
        return {
            "sql_validation": result,
            "status": RunStatus.REJECTED,
            "error": ErrorInfo(
                code="sql_policy_rejected",
                message="SQL was rejected by the deterministic safety policy.",
                retryable=False,
                details={"issue_codes": [issue.code for issue in result.issues]},
            ),
        }

    builder = StateGraph(RunState)
    builder.add_node("validate_sql", validate_sql)
    builder.add_edge(START, "validate_sql")
    builder.add_edge("validate_sql", END)
    return builder.compile()


SQLValidationGraphFactory = Callable[
    [SQLSafetyPolicy], CompiledStateGraph[RunState, None, RunState, RunState]
]
