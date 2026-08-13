"""Safe database adapter exceptions."""


class DatabaseAdapterError(RuntimeError):
    """Base exception whose message is safe to expose to an API error mapper."""


class UnsupportedDatabaseError(DatabaseAdapterError):
    """Raised when an adapter receives a connection URL for another database."""


class QueryPolicyError(DatabaseAdapterError):
    """Raised when deterministic SQL policy rejects a query."""


class QueryBudgetExceededError(DatabaseAdapterError):
    """Raised when PostgreSQL estimates a query above the configured cost budget."""


class ReadOnlyBoundaryError(DatabaseAdapterError):
    """Raised when the database does not confirm a read-only transaction."""
