from __future__ import annotations

from click.testing import CliRunner

from foundinspace.dust.cli import cli


def test_cli_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Dust map pipeline" in result.output


def test_rezaei2024_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["rezaei2024", "--help"])
    assert result.exit_code == 0
    assert "download" in result.output
    assert "build" in result.output


def test_mccallum2025_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["mccallum2025", "--help"])
    assert result.exit_code == 0
    assert "download" in result.output
    assert "build-tiled-volume" in result.output


def test_project_init(tmp_path) -> None:
    runner = CliRunner()
    out = tmp_path / "project.toml"
    result = runner.invoke(cli, ["project", "init", str(out)])
    assert result.exit_code == 0
    assert out.exists()
    assert "[rezaei2024]" in out.read_text()
    assert "[mccallum2025]" in out.read_text()
