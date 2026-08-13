"""Least-privilege PostgreSQL schema inspection and analytical execution."""

from collections.abc import Iterable
from hashlib import sha256
from time import perf_counter
from typing import Any

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import URL, Connection, make_url

from datapilot.adapters.database.errors import (
    QueryBudgetExceededError,
    QueryPolicyError,
    ReadOnlyBoundaryError,
    UnsupportedDatabaseError,
)
from datapilot.domain.query import QueryExecutionResult, QueryPlanSummary
from datapilot.domain.schema import (
    ColumnMetadata,
    ForeignKeyMetadata,
    SchemaSnapshot,
    TableMetadata,
)
from datapilot.domain.sql import SQLCandidate
from datapilot.policies.sql_safety import SQLSafetyPolicy


class PostgresAnalyticsDatabase:
    """PostgreSQL adapter that verifies read-only execution at runtime."""

    def __init__(
        self,
        database_url: str,
        *,
        policy: SQLSafetyPolicy,
        statement_timeout_ms: int = 15_000,
        max_estimated_cost: float = 100_000.0,
        engine: Engine | None = None,
    ) -> None:
        url = make_url(database_url)
        if url.get_backend_name() != "postgresql":
            raise UnsupportedDatabaseError("PostgresAnalyticsDatabase requires PostgreSQL.")
        if statement_timeout_ms < 100:
            raise ValueError("statement_timeout_ms must be at least 100")
        if max_estimated_cost <= 0:
            raise ValueError("max_estimated_cost must be positive")

        self._url: URL = url
        self._policy = policy
        self._statement_timeout_ms = statement_timeout_ms
        self._max_estimated_cost = max_estimated_cost
        self._engine = engine or create_engine(
            url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            pool_timeout=10,
            hide_parameters=True,
        )

    def close(self) -> None:
        """Release all pooled database connections."""

        self._engine.dispose()

    def check_connection(self) -> bool:
        """Return whether PostgreSQL accepts a minimal read-only probe."""

        with self._engine.connect() as connection:
            transaction = connection.begin()
            try:
                self._configure_read_only_transaction(connection)
                probe_result = connection.execute(text("SELECT 1")).scalar_one()
                return bool(probe_result == 1)
            finally:
                transaction.rollback()

    def inspect_schema(self, schema_names: Iterable[str]) -> SchemaSnapshot:
        """Return table, column, key, relationship, and comment metadata."""

        requested_schemas = tuple(dict.fromkeys(schema_names))
        if not requested_schemas:
            raise ValueError("at least one schema must be requested")

        tables: list[TableMetadata] = []
        with self._engine.connect() as connection:
            inspector = inspect(connection)
            for schema_name in requested_schemas:
                for table_name in sorted(inspector.get_table_names(schema=schema_name)):
                    column_comments = self._column_comments(
                        connection,
                        schema_name=schema_name,
                        table_name=table_name,
                    )
                    columns = tuple(
                        ColumnMetadata(
                            name=str(column["name"]),
                            data_type=str(column["type"]),
                            nullable=bool(column.get("nullable", True)),
                            default=self._optional_string(column.get("default")),
                            comment=column_comments.get(str(column["name"])),
                        )
                        for column in inspector.get_columns(table_name, schema=schema_name)
                    )
                    primary_key = inspector.get_pk_constraint(
                        table_name,
                        schema=schema_name,
                    )
                    foreign_keys = tuple(
                        ForeignKeyMetadata(
                            constrained_columns=tuple(foreign_key["constrained_columns"]),
                            referred_schema=foreign_key.get("referred_schema"),
                            referred_table=str(foreign_key["referred_table"]),
                            referred_columns=tuple(foreign_key["referred_columns"]),
                        )
                        for foreign_key in inspector.get_foreign_keys(
                            table_name,
                            schema=schema_name,
                        )
                    )
                    table_comment = inspector.get_table_comment(
                        table_name,
                        schema=schema_name,
                    ).get("text")
                    tables.append(
                        TableMetadata(
                            schema_name=schema_name,
                            table_name=table_name,
                            comment=self._optional_string(table_comment),
                            columns=columns,
                            primary_key=tuple(primary_key.get("constrained_columns") or ()),
                            foreign_keys=foreign_keys,
                        )
                    )

        return SchemaSnapshot(
            database_name=self._url.database or "unknown",
            tables=tuple(tables),
        )

    def execute(self, candidate: SQLCandidate) -> QueryExecutionResult:
        """Execute SQL using guarded or unrestricted behavior from the policy."""

        validation = self._policy.validate(candidate)
        if not validation.accepted or validation.normalized_sql is None:
            issue_codes = ", ".join(issue.code for issue in validation.issues)
            raise QueryPolicyError(f"SQL policy rejected the query: {issue_codes}")

        normalized_sql = validation.normalized_sql
        if not self._policy.enabled:
            return self._execute_unrestricted(normalized_sql)

        query_hash = sha256(normalized_sql.encode("utf-8")).hexdigest()
        started_at = perf_counter()

        with self._engine.connect() as connection:
            transaction = connection.begin()
            try:
                self._configure_read_only_transaction(connection)
                plan = self._explain(connection, normalized_sql)
                if plan.estimated_cost > self._max_estimated_cost:
                    raise QueryBudgetExceededError(
                        "Query estimated cost exceeds the configured execution budget."
                    )

                result = connection.execute(text(normalized_sql))
                columns = tuple(str(column) for column in result.keys())  # noqa: SIM118
                fetched_rows = result.fetchmany(self._policy.max_rows + 1)
                truncated = len(fetched_rows) > self._policy.max_rows
                rows = tuple(tuple(row) for row in fetched_rows[: self._policy.max_rows])
            finally:
                transaction.rollback()

        return QueryExecutionResult(
            query_hash=query_hash,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            duration_ms=(perf_counter() - started_at) * 1000,
            plan=plan,
        )

    def _execute_unrestricted(self, sql: str) -> QueryExecutionResult:
        query_hash = sha256(sql.encode("utf-8")).hexdigest()
        started_at = perf_counter()
        with self._engine.begin() as connection:
            result = connection.execute(text(sql))
            if result.returns_rows:
                columns = tuple(str(column) for column in result.keys())  # noqa: SIM118
                rows = tuple(tuple(row) for row in result.fetchall())
            else:
                columns = ()
                rows = ()

        return QueryExecutionResult(
            query_hash=query_hash,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=False,
            duration_ms=(perf_counter() - started_at) * 1000,
            plan=QueryPlanSummary(
                node_type="Unrestricted execution",
                estimated_cost=0,
                estimated_rows=len(rows),
            ),
        )

    def _configure_read_only_transaction(self, connection: Connection) -> None:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        connection.execute(
            text("SELECT set_config('statement_timeout', :timeout, true)"),
            {"timeout": f"{self._statement_timeout_ms}ms"},
        )
        is_read_only = connection.execute(
            text("SELECT current_setting('transaction_read_only')::boolean")
        ).scalar_one()
        if is_read_only is not True:
            raise ReadOnlyBoundaryError("PostgreSQL did not confirm a read-only transaction.")

    @staticmethod
    def _column_comments(
        connection: Connection,
        *,
        schema_name: str,
        table_name: str,
    ) -> dict[str, str]:
        rows = connection.execute(
            text(
                """
                SELECT a.attname AS column_name,
                       pg_catalog.col_description(a.attrelid, a.attnum) AS comment
                FROM pg_catalog.pg_attribute AS a
                JOIN pg_catalog.pg_class AS c ON c.oid = a.attrelid
                JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
                WHERE n.nspname = :schema_name
                  AND c.relname = :table_name
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                """
            ),
            {"schema_name": schema_name, "table_name": table_name},
        )
        return {str(row.column_name): str(row.comment) for row in rows if row.comment is not None}

    @staticmethod
    def _explain(connection: Connection, normalized_sql: str) -> QueryPlanSummary:
        raw_plan = connection.execute(text(f"EXPLAIN (FORMAT JSON) {normalized_sql}")).scalar_one()
        if isinstance(raw_plan, str):
            import json

            raw_plan = json.loads(raw_plan)
        plan_root: dict[str, Any] = raw_plan[0]["Plan"]
        return QueryPlanSummary(
            node_type=str(plan_root["Node Type"]),
            estimated_cost=float(plan_root["Total Cost"]),
            estimated_rows=int(plan_root["Plan Rows"]),
        )

    @staticmethod
    def _optional_string(value: object) -> str | None:
        return None if value is None else str(value)
