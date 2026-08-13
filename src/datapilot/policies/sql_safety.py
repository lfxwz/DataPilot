"""Defense-in-depth validation for model-generated analytical SQL."""

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from datapilot.domain.sql import (
    SQLCandidate,
    SQLRiskLevel,
    SQLValidationIssue,
    SQLValidationResult,
)

DEFAULT_BLOCKED_FUNCTIONS = frozenset(
    {
        "dblink",
        "dblink_connect",
        "dblink_exec",
        "lo_export",
        "lo_import",
        "pg_cancel_backend",
        "pg_ls_dir",
        "pg_read_binary_file",
        "pg_read_file",
        "pg_sleep",
        "pg_stat_file",
        "pg_terminate_backend",
        "set_config",
    }
)

DEFAULT_BLOCKED_SCHEMAS = frozenset({"information_schema", "pg_catalog"})


def _expression_types(*names: str) -> tuple[type[exp.Expression], ...]:
    """Resolve SQLGlot node types without coupling to one minor release."""

    resolved: list[type[exp.Expression]] = []
    for name in names:
        node_type = getattr(exp, name, None)
        if isinstance(node_type, type) and issubclass(node_type, exp.Expression):
            resolved.append(node_type)
    return tuple(resolved)


FORBIDDEN_NODE_TYPES = _expression_types(
    "Alter",
    "Analyze",
    "Attach",
    "Command",
    "Commit",
    "Copy",
    "Create",
    "Delete",
    "Detach",
    "Drop",
    "Grant",
    "Insert",
    "Into",
    "LoadData",
    "Lock",
    "Merge",
    "Pragma",
    "Revoke",
    "Rollback",
    "Set",
    "Transaction",
    "TruncateTable",
    "Update",
    "Use",
)


@dataclass(frozen=True, slots=True)
class SQLSafetyPolicy:
    """Validate and normalize analytical SQL before database execution.

    This policy is deliberately not treated as the primary security boundary.
    The executor must additionally use a database role that owns no objects and
    has only the minimum required ``SELECT`` privileges.
    """

    dialect: str = "postgres"
    max_rows: int = 1000
    enabled: bool = True
    allowed_schemas: frozenset[str] | None = None
    allowed_tables: frozenset[str] | None = None
    blocked_schemas: frozenset[str] = field(default_factory=lambda: DEFAULT_BLOCKED_SCHEMAS)
    blocked_functions: frozenset[str] = field(default_factory=lambda: DEFAULT_BLOCKED_FUNCTIONS)

    def __post_init__(self) -> None:
        if self.max_rows < 1:
            raise ValueError("max_rows must be positive")

    def validate(self, candidate: SQLCandidate) -> SQLValidationResult:
        """Return an immutable validation result without executing the SQL."""

        if not self.enabled:
            return SQLValidationResult(
                accepted=True,
                risk_level=SQLRiskLevel.HIGH,
                normalized_sql=candidate.sql,
            )

        issues: list[SQLValidationIssue] = []
        try:
            statements = sqlglot.parse(candidate.sql, read=candidate.dialect or self.dialect)
        except (ParseError, ValueError) as exc:
            return self._rejected("sql_parse_error", f"SQL could not be parsed: {exc}")

        if len(statements) != 1:
            return self._rejected(
                "multiple_statements",
                "Exactly one SQL statement is allowed per execution.",
            )

        statement = statements[0]
        if statement is None or not isinstance(statement, exp.Query):
            return self._rejected(
                "non_query_statement",
                "Only read-only SELECT queries are accepted.",
            )

        if FORBIDDEN_NODE_TYPES and any(statement.find_all(*FORBIDDEN_NODE_TYPES)):
            issues.append(
                SQLValidationIssue(
                    code="forbidden_operation",
                    message="The query contains a prohibited SQL operation.",
                )
            )

        cte_names = {
            cte.alias_or_name.casefold() for cte in statement.find_all(exp.CTE) if cte.alias_or_name
        }
        referenced_tables: set[str] = set()
        for table in statement.find_all(exp.Table):
            table_name = table.name
            if not table_name or table_name.casefold() in cte_names:
                continue

            schema_name = table.db
            qualified_name = (
                f"{schema_name}.{table_name}" if schema_name else table_name
            ).casefold()
            referenced_tables.add(qualified_name)

            if schema_name and schema_name.casefold() in self.blocked_schemas:
                issues.append(
                    SQLValidationIssue(
                        code="blocked_schema",
                        message=f"Schema {schema_name!r} is not available to analytical queries.",
                    )
                )
            if (
                self.allowed_schemas is not None
                and schema_name
                and schema_name.casefold() not in self._casefolded(self.allowed_schemas)
            ):
                issues.append(
                    SQLValidationIssue(
                        code="schema_not_allowed",
                        message=f"Schema {schema_name!r} is outside the configured allowlist.",
                    )
                )
            if (
                self.allowed_tables is not None
                and qualified_name not in self._casefolded(self.allowed_tables)
                and table_name.casefold() not in self._casefolded(self.allowed_tables)
            ):
                issues.append(
                    SQLValidationIssue(
                        code="table_not_allowed",
                        message=f"Table {qualified_name!r} is outside the configured allowlist.",
                    )
                )

        blocked_functions = self._casefolded(self.blocked_functions)
        for function in statement.find_all(exp.Func):
            function_name = self._function_name(function)
            if function_name and function_name in blocked_functions:
                issues.append(
                    SQLValidationIssue(
                        code="blocked_function",
                        message=f"Function {function_name!r} is prohibited by policy.",
                    )
                )

        if issues:
            return SQLValidationResult(
                accepted=False,
                risk_level=SQLRiskLevel.HIGH,
                referenced_tables=tuple(sorted(referenced_tables)),
                issues=tuple(self._deduplicate_issues(issues)),
            )

        normalized = statement.copy()
        normalized = self._apply_row_limit(normalized)
        return SQLValidationResult(
            accepted=True,
            risk_level=self._classify_complexity(statement),
            normalized_sql=normalized.sql(dialect=self.dialect, pretty=True),
            referenced_tables=tuple(sorted(referenced_tables)),
        )

    def _apply_row_limit(self, statement: exp.Query) -> exp.Query:
        limit = statement.args.get("limit")
        if limit is None:
            return statement.limit(self.max_rows)

        expression = limit.expression
        if isinstance(expression, exp.Literal) and not expression.is_string:
            try:
                requested_limit = int(expression.this)
            except (TypeError, ValueError):
                requested_limit = self.max_rows
            if requested_limit > self.max_rows:
                return statement.limit(self.max_rows, copy=False)
        return statement

    @staticmethod
    def _function_name(function: exp.Func) -> str:
        if isinstance(function, exp.Anonymous):
            return function.name.casefold()
        sql_name = function.sql_name()  # type: ignore[no-untyped-call]
        return str(sql_name).casefold()

    @staticmethod
    def _casefolded(values: frozenset[str]) -> frozenset[str]:
        return frozenset(value.casefold() for value in values)

    @staticmethod
    def _deduplicate_issues(
        issues: list[SQLValidationIssue],
    ) -> list[SQLValidationIssue]:
        unique: dict[tuple[str, str], SQLValidationIssue] = {}
        for issue in issues:
            unique[(issue.code, issue.message)] = issue
        return list(unique.values())

    @staticmethod
    def _classify_complexity(statement: exp.Query) -> SQLRiskLevel:
        joins = sum(1 for _ in statement.find_all(exp.Join))
        windows = sum(1 for _ in statement.find_all(exp.Window))
        subqueries = sum(1 for _ in statement.find_all(exp.Subquery))
        return (
            SQLRiskLevel.MEDIUM if joins >= 2 or windows > 0 or subqueries > 0 else SQLRiskLevel.LOW
        )

    @staticmethod
    def _rejected(code: str, message: str) -> SQLValidationResult:
        return SQLValidationResult(
            accepted=False,
            risk_level=SQLRiskLevel.HIGH,
            issues=(SQLValidationIssue(code=code, message=message),),
        )
