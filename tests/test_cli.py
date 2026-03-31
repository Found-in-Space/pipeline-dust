from __future__ import annotations

from click.testing import CliRunner

from pipeline_dust.cli import cli


def test_cli_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Dust map pipeline" in result.output


def test_hello() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["hello"])
    assert result.exit_code == 0
    assert "pipeline-dust" in result.output
