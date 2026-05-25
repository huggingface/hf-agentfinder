from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from agentfinder.challenge import create_challenge_app
from agentfinder.hf_skills import search_hf_skills
from agentfinder.hf_spaces import (
    AI_SKILL_MEDIA_TYPE,
    DEFAULT_BASE_URL,
    HF_SPACE_MEDIA_TYPE,
    MCP_SERVER_MEDIA_TYPE,
    SpaceResultKind,
    SpaceSearcher,
    search_hf_spaces,
)
from agentfinder.models import SearchQuery, SearchRequest, SearchResponse, SearchResult
from agentfinder.server import create_app

console = Console()
PACKAGE_NAME = "hf-agentfinder"
SPEC_HELP = """Agent Finder discovers agent capabilities through REST registries.

Search sends POST /search with {"query":{"text": "...", "mediaType": optional,
"federation": "none|referrals|auto"}, "pageSize": n} and receives a SearchResponse
containing results, optional referrals, and an optional pageToken.

Each result is an ai-catalog entry plus score/source. Use mediaType to decide how to
consume it: application/ai-skill, application/mcp-server+json,
application/a2a-agent-card+json, application/ai-catalog+json, or
application/ai-registry+json. Entries contain exactly one of url or data. Fetch url
artifacts directly; parse data inline. For application/ai-registry+json result or
referral URLs, search that registry next (the URL may already be a /search endpoint).
"""

app = typer.Typer(
    help=f"Agent Finder registry adapters.\n\n{SPEC_HELP}",
    epilog=(
        "Challenge quickstart: run `agentfinder challenge serve --port 8090`, then "
        '`agentfinder challenge search "find tools" --federation referrals --json`. '
        "Generic registry search: `agentfinder search --registry-url URL QUERY`."
    ),
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=True,
)
spaces_app = typer.Typer(
    help=f"Search and expose Hugging Face Spaces as Agent Finder results.\n\n{SPEC_HELP}",
    add_completion=False,
)
challenge_app = typer.Typer(
    help=(
        "Run and query deterministic Agent Finder challenge fixtures.\n\n"
        "The challenge server is intentionally useful for agents learning the spec: "
        "it returns skills, MCP servers, A2A agents, inline ai-catalog bundles, "
        "ai-registry entries, referrals, empty registries, and nested registries."
    ),
    add_completion=False,
)
app.add_typer(spaces_app, name="spaces")
app.add_typer(challenge_app, name="challenge")

VersionOpt = Annotated[
    bool,
    typer.Option(
        "--version",
        help="Show the installed hf-agentfinder version and exit.",
        is_eager=True,
    ),
]
QueryArg = Annotated[str, typer.Argument(help="Natural-language Agent Finder search query.")]
FederationMode = Literal["auto", "referrals", "none"]
LimitOpt = Annotated[int, typer.Option("--limit", "-n", min=1, max=100, help="Maximum results.")]
SdkOpt = Annotated[
    list[str] | None,
    typer.Option("--sdk", help="Filter by Space SDK. May be passed multiple times."),
]
FilterOpt = Annotated[
    list[str] | None,
    typer.Option("--filter", "-f", help="Filter by Space tag. May be passed multiple times."),
]
TokenOpt = Annotated[
    str | None,
    typer.Option(
        "--token",
        help="Hugging Face access token, or registry Bearer token when --registry-url is used.",
    ),
]
RegistryUrlOpt = Annotated[
    str | None,
    typer.Option(
        "--registry-url",
        help=(
            "Agent Finder registry URL to query instead of Hugging Face Spaces. "
            "May be a registry base URL or its /search endpoint."
        ),
    ),
]
IncludeNonRunningOpt = Annotated[
    bool,
    typer.Option("--include-non-running", help="Include Spaces that are not currently running."),
]
JsonOpt = Annotated[bool, typer.Option("--json", help="Emit Agent Finder JSON response.")]
FederationOpt = Annotated[
    FederationMode,
    typer.Option(
        "--federation",
        case_sensitive=False,
        help=(
            "Agent Finder federation mode to send in SearchRequest.query: none, "
            "referrals, or auto. Use referrals/auto to ask registries for registry "
            "referrals that a client can search next."
        ),
    ),
]
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


@dataclass(frozen=True)
class RegistrySearchResult:
    response: SearchResponse
    raw_body: str


def _project_version() -> str:
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return "unknown"


def _print_version() -> None:
    console.print(f"agentfinder {_project_version()}")


@app.callback()
def main(version_requested: VersionOpt = False) -> None:
    """Agent Finder registry adapters."""
    if version_requested:
        _print_version()
        raise typer.Exit


@app.command("version")
def version_command() -> None:
    """Show the installed hf-agentfinder version."""
    _print_version()


def _registry_search_url(registry_url: str) -> str:
    normalized = registry_url.rstrip("/")
    if normalized.endswith("/search"):
        return normalized
    return urljoin(f"{normalized}/", "search")


def _media_type_for_kind(kind: SpaceResultKind) -> str | None:
    media_types: dict[SpaceResultKind, str | None] = {
        "all": None,
        "skill": AI_SKILL_MEDIA_TYPE,
        "mcp": MCP_SERVER_MEDIA_TYPE,
        "space": HF_SPACE_MEDIA_TYPE,
    }
    return media_types[kind]


def _registry_search(
    registry_url: str,
    query: str,
    *,
    limit: int,
    kind: SpaceResultKind = "all",
    federation: FederationMode = "none",
    token: str | None = None,
) -> RegistrySearchResult:
    request_body = SearchRequest(
        query=SearchQuery(text=query, mediaType=_media_type_for_kind(kind), federation=federation),
        pageSize=limit,
    )
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "agentfinder/0.1",
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"

    request = UrlRequest(  # noqa: S310 - user-supplied registry URL is the point.
        _registry_search_url(registry_url),
        data=request_body.model_dump_json(exclude_none=True, exclude_defaults=True).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310
            raw_body = response.read().decode("utf-8")
            return RegistrySearchResult(
                response=SearchResponse.model_validate_json(raw_body),
                raw_body=raw_body,
            )
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise typer.BadParameter(
            f"registry search failed with HTTP {exc.code}: {detail}",
            param_hint="--registry-url",
        ) from exc
    except (URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        raise typer.BadParameter(
            f"registry search failed: {exc}",
            param_hint="--registry-url",
        ) from exc


def _registry_search_response(
    registry_url: str,
    query: str,
    *,
    limit: int,
    kind: SpaceResultKind = "all",
    federation: FederationMode = "none",
    token: str | None = None,
) -> SearchResponse:
    return _registry_search(
        registry_url,
        query,
        limit=limit,
        kind=kind,
        federation=federation,
        token=token,
    ).response


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


def _skills_search_response(
    query: str,
    *,
    limit: int,
    kind: SpaceResultKind = "all",
) -> SearchResponse:
    if kind not in {"all", "skill"}:
        return SearchResponse(results=[])
    return SearchResponse(results=search_hf_skills(query, limit=limit))


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


def _print_results(response: SearchResponse, *, title: str = "Search Results") -> None:
    table = Table(title=title)
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


def _print_raw_json(raw_body: str) -> None:
    console.file.write(raw_body)
    console.file.write("\n")


@app.command("search")
def search_alias(  # noqa: PLR0913 - Typer command surface intentionally maps CLI options.
    query: QueryArg,
    limit: LimitOpt = 10,
    sdk: SdkOpt = None,
    filters: FilterOpt = None,
    include_non_running: IncludeNonRunningOpt = False,
    token: TokenOpt = None,
    registry_url: RegistryUrlOpt = None,
    federation: FederationOpt = "none",
    json_output: JsonOpt = False,
    base_url: BaseUrlOpt = DEFAULT_BASE_URL,
    kind: KindOpt = "all",
) -> None:
    """Search Skills or any Agent Finder registry.

    Remote registry mode POSTs an Agent Finder SearchRequest to --registry-url. With
    --json, the CLI prints the registry's raw SearchResponse bytes instead of a
    normalized/re-serialized model, so reading agents can inspect exact result, referral,
    url, data, mediaType, and pageToken fields returned by the server.
    """
    if registry_url is None:
        _ = sdk, filters, include_non_running, token, base_url, federation
        response = _skills_search_response(query, limit=limit, kind=kind)
        raw_body = response.model_dump_json(exclude_none=True, exclude_defaults=True)
        title = "Hugging Face Skills"
    else:
        registry_result = _registry_search(
            registry_url,
            query,
            limit=limit,
            kind=kind,
            federation=federation,
            token=token,
        )
        response = registry_result.response
        raw_body = registry_result.raw_body
        title = registry_url

    if json_output:
        _print_raw_json(raw_body)
    else:
        _print_results(response, title=title)


@spaces_app.command("search")
def spaces_search(  # noqa: PLR0913 - Typer command surface intentionally maps CLI options.
    query: QueryArg,
    limit: LimitOpt = 10,
    sdk: SdkOpt = None,
    filters: FilterOpt = None,
    include_non_running: IncludeNonRunningOpt = False,
    token: TokenOpt = None,
    registry_url: RegistryUrlOpt = None,
    federation: FederationOpt = "none",
    json_output: JsonOpt = False,
    base_url: BaseUrlOpt = DEFAULT_BASE_URL,
    kind: KindOpt = "all",
) -> None:
    """Search Hugging Face Spaces or a remote Agent Finder registry.

    Spec navigation: inspect each result's mediaType, then consume exactly one of url or
    data. Search application/ai-registry+json URLs again to walk registry trees. Use
    --federation referrals when querying registries that can suggest other registries.
    """
    if registry_url is None:
        _ = federation
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
        raw_body = response.model_dump_json(exclude_none=True, exclude_defaults=True)
        title = "Hugging Face Spaces"
    else:
        registry_result = _registry_search(
            registry_url,
            query,
            limit=limit,
            kind=kind,
            federation=federation,
            token=token,
        )
        response = registry_result.response
        raw_body = registry_result.raw_body
        title = registry_url

    if json_output:
        _print_raw_json(raw_body)
    else:
        _print_results(response, title=title)


@challenge_app.command("search")
def challenge_search(
    query: QueryArg,
    registry_url: Annotated[
        str,
        typer.Option(
            "--registry-url",
            help=(
                "Challenge registry URL. May be the server base URL or a nested /search URL "
                "such as http://127.0.0.1:8090/registries/tools/search."
            ),
        ),
    ] = "http://127.0.0.1:8090",
    limit: LimitOpt = 10,
    kind: KindOpt = "all",
    federation: FederationOpt = "referrals",
    json_output: JsonOpt = False,
) -> None:
    """Query a running challenge server.

    Defaults to the local `agentfinder challenge serve` endpoint and requests referrals.
    Reading agents should use --json to see the raw SearchResponse, follow referrals and
    application/ai-registry+json result URLs, fetch url artifacts, and parse inline data.
    """
    registry_result = _registry_search(
        registry_url,
        query,
        limit=limit,
        kind=kind,
        federation=federation,
    )
    if json_output:
        _print_raw_json(registry_result.raw_body)
    else:
        _print_results(registry_result.response, title=registry_url)


@app.command("serve")
def serve(
    host: Annotated[str, typer.Option("--host", help="Host to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p", help="Port to bind.")] = 8080,
    include_non_running: IncludeNonRunningOpt = False,
    token: TokenOpt = None,
) -> None:
    """Serve Agent Finder registries for Hugging Face Skills and Spaces."""
    uvicorn.run(
        create_app(include_non_running=include_non_running, token=token),
        host=host,
        port=port,
    )


@challenge_app.command("serve")
def challenge_serve(
    host: Annotated[str, typer.Option("--host", help="Host to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p", help="Port to bind.")] = 8090,
) -> None:
    """Serve deterministic mixed Agent Finder fixtures for client development."""
    uvicorn.run(create_challenge_app(), host=host, port=port)
