"""Typed application configuration loaded exclusively from the environment."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Validated runtime settings.

    Secrets use ``SecretStr`` so accidental logging renders them redacted.
    Production deployments should inject values through a secret manager.
    """

    model_config = SettingsConfigDict(
        env_prefix="DATAPILOT_",
        env_file=_PROJECT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)
    cors_allowed_origins: tuple[str, ...] = (
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )

    database_url: SecretStr | None = None
    metadata_database_url: SecretStr | None = None
    enable_query_api: bool = False
    enable_agent_api: bool = False
    sql_safety_enabled: bool = True
    sql_dialect: str = "postgres"
    sql_allowed_schemas: tuple[str, ...] = ("olist",)
    sql_max_rows: int = Field(default=1000, ge=1, le=100_000)
    sql_statement_timeout_ms: int = Field(default=15_000, ge=100, le=300_000)
    sql_max_estimated_cost: float = Field(default=100_000.0, gt=0, le=100_000_000)
    sql_max_retries: int = Field(default=2, ge=0, le=5)

    llm_base_url: str | None = "https://api.deepseek.com"
    llm_api_key: SecretStr | None = None
    llm_credentials_file: Path | None = None
    llm_credentials_variable: str = "OPENAI_API_KEY"
    llm_model: str | None = "deepseek-v4-flash"
    llm_timeout_seconds: float = Field(default=60.0, ge=1, le=300)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    llm_thinking_enabled: bool = False

    enable_generated_python: bool = False
    sandbox_container_name: str = "datapilot-python-runtime"
    sandbox_timeout_seconds: int = Field(default=45, ge=1, le=300)
    sandbox_memory_mb: int = Field(default=768, ge=128, le=16_384)
    sandbox_cpu_count: float = Field(default=1.0, gt=0, le=16)

    @field_validator("llm_credentials_file", mode="before")
    @classmethod
    def normalize_optional_path(cls, value: object) -> object:
        """Treat an empty environment value as an absent optional path."""

        return None if value == "" else value

    @property
    def llm_is_configured(self) -> bool:
        """Return whether all provider settings needed for an LLM call exist."""

        credential_source = self.llm_api_key or self.llm_credentials_file
        return all((self.llm_base_url, credential_source, self.llm_model))

    @property
    def metadata_is_configured(self) -> bool:
        return self.metadata_database_url is not None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide validated settings instance."""

    return Settings()
