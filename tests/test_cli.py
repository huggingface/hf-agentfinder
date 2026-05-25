from __future__ import annotations

from importlib.metadata import entry_points, version

from typer.testing import CliRunner

from agentfinder.cli import app


def test_version_option_prints_installed_project_version() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output == f"agentfinder {version('hf-agentfinder')}\n"


def test_version_command_prints_installed_project_version() -> None:
    result = CliRunner().invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.output == f"agentfinder {version('hf-agentfinder')}\n"


def test_package_exposes_hf_extension_console_script() -> None:
    scripts = entry_points(group="console_scripts")

    assert scripts["agentfinder"].value == "agentfinder.cli:app"
    assert scripts["hf-agentfinder"].value == "agentfinder.cli:app"
