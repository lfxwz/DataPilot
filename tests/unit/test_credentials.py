"""Tests for safe literal-only local credential loading."""

from pathlib import Path

import pytest

from datapilot.services.credentials import (
    CredentialConfigurationError,
    read_literal_assignment,
)


def test_reads_literal_secret_without_executing_file(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist.txt"
    config = tmp_path / "config.py"
    config.write_text(
        f"OPENAI_API_KEY = 'test-secret'\nopen({str(marker)!r}, 'w').write('executed')\n",
        encoding="utf-8",
    )

    assert read_literal_assignment(config, "OPENAI_API_KEY") == "test-secret"
    assert marker.exists() is False


def test_rejects_computed_or_missing_credentials(tmp_path: Path) -> None:
    config = tmp_path / "config.py"
    config.write_text("OPENAI_API_KEY = make_secret()\n", encoding="utf-8")

    with pytest.raises(CredentialConfigurationError, match="literal string"):
        read_literal_assignment(config, "OPENAI_API_KEY")
    with pytest.raises(CredentialConfigurationError, match="was not found"):
        read_literal_assignment(Path(__file__), "NOT_A_REAL_VARIABLE")
