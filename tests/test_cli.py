from __future__ import annotations

from importlib.metadata import entry_points, version
from inspect import signature
from typing import Any, cast

from pydantic import ValidationError
from typer.main import get_command
from typer.testing import CliRunner

from agentfinder import cli
from agentfinder.models import SearchResponse

app = cli.app


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


def test_search_commands_default_to_hosted_registry_urls() -> None:
    search_parameters = signature(cli.search_alias).parameters

    assert search_parameters["registry_url"].default == cli.DEFAULT_REGISTRY_URL
    assert search_parameters["base_url"].default == cli.DEFAULT_REGISTRY_URL
    assert search_parameters["local"].default is False


def test_search_command_hides_local_base_url_escape_hatch() -> None:
    command = cast("Any", get_command(app)).commands["search"]
    options_by_name = {parameter.name: parameter for parameter in command.params}

    assert options_by_name["registry_url"].hidden is False
    assert options_by_name["local"].hidden is False
    assert options_by_name["base_url"].hidden is True


def test_registry_response_error_message_explains_missing_v5_type_field() -> None:
    try:
        SearchResponse.model_validate(
            {
                "results": [
                    {
                        "identifier": "urn:ai:example:skill",
                        "displayName": "Example Skill",
                        "url": "https://example.com/SKILL.md",
                        "score": 91,
                        "source": "https://example.com",
                    }
                ]
            }
        )
    except ValidationError as exc:
        message = cli._registry_response_error_message(exc)
    else:
        raise AssertionError("expected malformed SearchResponse to fail validation")

    assert "not an Agent Finder v0.5 SearchResponse" in message
    assert "results.0.type" in message
    assert "include `type` media types" in message
    assert "older pre-v0.5 schema" in message


def test_registry_response_error_message_summarizes_many_missing_fields() -> None:
    try:
        SearchResponse.model_validate(
            {
                "results": [
                    {
                        "identifier": f"urn:ai:example:skill:{index}",
                        "displayName": f"Example Skill {index}",
                        "url": f"https://example.com/{index}/SKILL.md",
                        "score": 91,
                        "source": "https://example.com",
                    }
                    for index in range(6)
                ]
            }
        )
    except ValidationError as exc:
        message = cli._registry_response_error_message(exc)
    else:
        raise AssertionError("expected malformed SearchResponse to fail validation")

    assert "results.0.type" in message
    assert "results.4.type" in message
    assert "results.5.type" not in message
    assert "(6 total)" in message
