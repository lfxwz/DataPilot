"""Tests for environment-backed settings and secret handling."""

from pydantic import SecretStr

from datapilot.config import Settings


def test_secret_values_render_redacted() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:password@example.test/database",
        metadata_database_url="postgresql://metadata:password@example.test/database",
        llm_base_url="https://llm.example.test/v1",
        llm_api_key="top-secret",
        llm_model="example-model",
    )

    assert isinstance(settings.database_url, SecretStr)
    assert str(settings.database_url) == "**********"
    assert str(settings.metadata_database_url) == "**********"
    assert str(settings.llm_api_key) == "**********"
    assert settings.llm_is_configured is True
    assert settings.metadata_is_configured is True


def test_partial_llm_configuration_is_not_ready() -> None:
    settings = Settings(_env_file=None, llm_model="example-model")

    assert settings.llm_is_configured is False


def test_public_olist_schema_is_the_default_allowlist() -> None:
    settings = Settings(_env_file=None)

    assert settings.sql_safety_enabled is True
    assert settings.sql_allowed_schemas == ("olist",)
    assert settings.sandbox_container_name == "datapilot-python-runtime"


def test_empty_optional_credential_path_does_not_enable_llm() -> None:
    settings = Settings(_env_file=None, llm_credentials_file="")

    assert settings.llm_credentials_file is None
    assert settings.llm_is_configured is False
