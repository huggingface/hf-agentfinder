from __future__ import annotations

from typing import Annotated

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from agentfinder.hf_spaces import (
    AI_SKILL_MEDIA_TYPE,
    DEFAULT_BASE_URL,
    HF_SPACE_MEDIA_TYPE,
    MCP_SERVER_MEDIA_TYPE,
    SpaceResultKind,
    SpaceSearcher,
    search_hf_spaces,
)
from agentfinder.models import SearchResponse, SearchResult
from agentfinder.server import create_app

console = Console()
app = typer.Typer(help="Agent Finder registry adapters.", add_completion=False)
spaces_app = typer.Typer(help="Search and expose Hugging Face Spaces.", add_completion=False)
app.add_typer(spaces_app, name="spaces")

QueryArg = Annotated[str, typer.Argument(help="Natural-language Spaces search query.")]
LimitOpt = Annotated[int, typer.Option("--limit", "-n", min=1, max=100, help="Maximum results.")]
SdkOpt = Annotated[
    list[str] | None,
    typer.Option("--sdk", help="Filter by Space SDK. May be passed multiple times."),
]
FilterOpt = Annotated[
    list[str] | None,
    typer.Option("--filter", "-f", help="Filter by Space tag. May be passed multiple times."),
]
TokenOpt = Annotated[str | None, typer.Option("--token", help="Hugging Face access token.")]
IncludeNonRunningOpt = Annotated[
    bool,
    typer.Option("--include-non-running", help="Include Spaces that are not currently running."),
]
JsonOpt = Annotated[bool, typer.Option("--json", help="Emit Agent Finder JSON response.")]
BaseUrlOpt = Annotated[
    str,
    typer.Option("--base-url", help="Base URL used for generated skill artifact URLs."),
]
KindOpt = Annotated[
    SpaceResultKind,
    typer.Option(
        "--kind",
        case_sensitive=False,
        help=(
            "Result artifact kind: skill, mcp, space, or all. "
            "The 'all' kind can return both skill and MCP entries for one Space."
        ),
    ),
]


def _search_response(
    query: str,
    *,
    limit: int,
    sdk: list[str] | None,
    filters: list[str] | None,
    include_non_running: bool,
    token: str | None,
    base_url: str,
    kind: SpaceResultKind = "all",
    searcher: SpaceSearcher | None = None,
) -> SearchResponse:
    return SearchResponse(
        results=search_hf_spaces(
            query,
            limit=limit,
            sdk=sdk,
            filters=filters,
            include_non_running=include_non_running,
            token=token,
            base_url=base_url,
            kind=kind,
            searcher=searcher,
        )
    )


def _result_type(result: SearchResult) -> str:
    if result.mediaType == AI_SKILL_MEDIA_TYPE:
        return "skill"
    if result.mediaType == MCP_SERVER_MEDIA_TYPE:
        return "mcp"
    if result.mediaType == HF_SPACE_MEDIA_TYPE:
        return "space"
    return result.mediaType


def _string_data_value(result: SearchResult, key: str) -> str:
    if result.data is None:
        return ""
    value = result.data.get(key)
    return value if isinstance(value, str) else ""


def _result_endpoint(result: SearchResult) -> str:
    if result.url is not None:
        return result.url
    return (
        _string_data_value(result, "url")
        or _string_data_value(result, "appUrl")
        or _string_data_value(result, "hubUrl")
    )


def _print_results(response: SearchResponse) -> None:
    table = Table(title="Hugging Face Spaces")
    table.add_column("#", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Type")
    table.add_column("Name")
    table.add_column("SDK")
    table.add_column("Stage")
    table.add_column("Endpoint")
    table.add_column("Description")

    for index, result in enumerate(response.results, 1):
        sdk = result.metadata.get("sdk")
        stage = result.metadata.get("runtimeStage")
        table.add_row(
            str(index),
            f"{result.score:.1f}",
            _result_type(result),
            result.displayName,
            sdk if isinstance(sdk, str) else "",
            stage if isinstance(stage, str) else "",
            _result_endpoint(result),
            result.description or "",
        )
    console.print(table)


@app.command("search")
def search_alias(
    query: QueryArg,
    limit: LimitOpt = 10,
    sdk: SdkOpt = None,
    filters: FilterOpt = None,
    include_non_running: IncludeNonRunningOpt = False,
    token: TokenOpt = None,
    json_output: JsonOpt = False,
    base_url: BaseUrlOpt = DEFAULT_BASE_URL,
    kind: KindOpt = "all",
) -> None:
    """Search Hugging Face Spaces and return Agent Finder-shaped results."""
    response = _search_response(
        query,
        limit=limit,
        sdk=sdk,
        filters=filters,
        include_non_running=include_non_running,
        token=token,
        base_url=base_url,
        kind=kind,
    )
    if json_output:
        console.print_json(response.model_dump_json(exclude_none=True, exclude_defaults=True))
    else:
        _print_results(response)


@spaces_app.command("search")
def spaces_search(
    query: QueryArg,
    limit: LimitOpt = 10,
    sdk: SdkOpt = None,
    filters: FilterOpt = None,
    include_non_running: IncludeNonRunningOpt = False,
    token: TokenOpt = None,
    json_output: JsonOpt = False,
    base_url: BaseUrlOpt = DEFAULT_BASE_URL,
    kind: KindOpt = "all",
) -> None:
    """Search Hugging Face Spaces and return Agent Finder-shaped results."""
    search_alias(
        query=query,
        limit=limit,
        sdk=sdk,
        filters=filters,
        include_non_running=include_non_running,
        token=token,
        json_output=json_output,
        base_url=base_url,
        kind=kind,
    )


@app.command("serve")
def serve(
    host: Annotated[str, typer.Option("--host", help="Host to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p", help="Port to bind.")] = 8080,
    include_non_running: IncludeNonRunningOpt = False,
    token: TokenOpt = None,
) -> None:
    """Serve a thin Agent Finder REST wrapper over Hugging Face Spaces search."""
    uvicorn.run(
        create_app(include_non_running=include_non_running, token=token),
        host=host,
        port=port,
    )
