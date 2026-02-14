"""Tests for CLI entry point."""

from __future__ import annotations

from click.testing import CliRunner

from blunder_butler.cli import main


def test_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "USERNAME" in result.output
    assert "--time-control" in result.output
    assert "--engine-time-ms" in result.output
    assert "--max-games" in result.output


def test_no_args():
    runner = CliRunner()
    result = runner.invoke(main, [])
    assert result.exit_code != 0
    assert "Missing argument" in result.output


def test_all_options_listed():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    expected_options = [
        "--time-control",
        "--since",
        "--max-games",
        "--rated-only",
        "--engine-time-ms",
        "--depth",
        "--engine-path",
        "--threads",
        "--workers",
        "--both-sides",
        "--llm",
        "--resume",
        "--output-dir",
        "--verbose",
        "--blunder-threshold",
    ]
    for opt in expected_options:
        assert opt in result.output, f"Missing option: {opt}"
