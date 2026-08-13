"""Explicit secret resolution without importing or executing credential files."""

import ast
from pathlib import Path

from pydantic import SecretStr

from datapilot.config import Settings


class CredentialConfigurationError(RuntimeError):
    """Raised when configured credentials cannot be loaded safely."""


def resolve_llm_api_key(settings: Settings) -> SecretStr:
    """Resolve the direct setting or a literal assignment in a local Python config."""

    if settings.llm_api_key is not None:
        return settings.llm_api_key
    if settings.llm_credentials_file is None:
        raise CredentialConfigurationError("No LLM API credential source is configured.")
    value = read_literal_assignment(
        settings.llm_credentials_file,
        settings.llm_credentials_variable,
    )
    return SecretStr(value)


def read_literal_assignment(path: Path, variable_name: str) -> str:
    """Read one top-level string assignment using AST; never execute the file."""

    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CredentialConfigurationError(
            "The configured LLM credential file is unavailable."
        ) from exc

    try:
        module = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise CredentialConfigurationError(
            "The configured LLM credential file is invalid."
        ) from exc

    for statement in module.body:
        if isinstance(statement, ast.Assign):
            names = [target.id for target in statement.targets if isinstance(target, ast.Name)]
            if variable_name in names:
                return _literal_secret(statement.value, variable_name)
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == variable_name
            and statement.value is not None
        ):
            return _literal_secret(statement.value, variable_name)
    raise CredentialConfigurationError(
        f"Credential variable {variable_name!r} was not found in the configured file."
    )


def _literal_secret(node: ast.expr, variable_name: str) -> str:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError) as exc:
        raise CredentialConfigurationError(
            f"Credential variable {variable_name!r} must be a literal string."
        ) from exc
    if not isinstance(value, str) or not value.strip():
        raise CredentialConfigurationError(
            f"Credential variable {variable_name!r} must be a non-empty string."
        )
    return value
