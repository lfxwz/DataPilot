"""Database schema metadata used for grounded SQL generation."""

from datetime import datetime

from pydantic import Field

from datapilot.domain.common import StrictModel, utc_now


class ColumnMetadata(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    data_type: str = Field(min_length=1, max_length=500)
    nullable: bool
    default: str | None = Field(default=None, max_length=2000)
    comment: str | None = Field(default=None, max_length=4000)


class ForeignKeyMetadata(StrictModel):
    constrained_columns: tuple[str, ...] = Field(min_length=1)
    referred_schema: str | None = None
    referred_table: str = Field(min_length=1, max_length=255)
    referred_columns: tuple[str, ...] = Field(min_length=1)


class TableMetadata(StrictModel):
    schema_name: str = Field(min_length=1, max_length=255)
    table_name: str = Field(min_length=1, max_length=255)
    comment: str | None = Field(default=None, max_length=4000)
    columns: tuple[ColumnMetadata, ...]
    primary_key: tuple[str, ...] = ()
    foreign_keys: tuple[ForeignKeyMetadata, ...] = ()

    @property
    def qualified_name(self) -> str:
        return f"{self.schema_name}.{self.table_name}"


class SchemaSnapshot(StrictModel):
    """A versionable snapshot returned to schema-selection components."""

    database_name: str = Field(min_length=1, max_length=255)
    captured_at: datetime = Field(default_factory=utc_now)
    tables: tuple[TableMetadata, ...]
