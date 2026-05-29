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
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from agentfinder.challenge import create_challenge_app
from agentfinder.hf_skills import search_hf_skills
from agentfinder.hf_spaces import (
    AI_SKILL_MEDIA_TYPE,
    DEFAULT_BASE_URL,
    HF_SPACE_MEDIA_TYPE,
    MCP_SERVER_MEDIA_TYPE,
    SPACES_URL_PREFIX,
    SpaceResultKind,
    SpaceSearcher,
    search_hf_spaces,
)
from agentfinder.models import SearchQuery, SearchRequest, SearchResponse, SearchResult
from agentfinder.server import create_app

console = Console()
PACKAGE_NAME = "hf-agentfinder"
DEFAULT_REGISTRY_URL = SPACES_URL_PREFIX
ERROR_FIELD_PREVIEW_LIMIT = 5
SPEC_HELP = """Find agent-ready Hugging Face Skills, Spaces, Servers.

Search the registry and output Agent Finder results as JSON or human readable tables.

Find background removal MCP Servers:
hf-agentfinder search "remove image background" --json --kind mcp

Find AI Skills or MCP Servers to train a vision model:
hf-agentfinder search "train a vision model" --json

Use --kind skill|space|mcp to search for a specific result view:
  skill: AI skills, including indexed Hugging Face Skills and generated Space SKILL.md wrappers
  space: raw Hugging Face Space descriptors
  mcp: MCP server entries for Spaces tagged mcp-server
Use hf-agentfinder search --help for more information.

"""

app = typer.Typer(
    help=f"Agent Finder registry adapters.\n\n{SPEC_HELP}",
    # epilog=(
    #     "Challenge quickstart: run `agentfinder challenge serve --port 8090`, then "
    #     '`agentfinder challenge search "find tools" --federation referrals --json`. '
    #     "Hosted registry search: `agentfinder search QUERY`. "
    #     "Generic registry search: `agentfinder search --registry-url URL QUERY`."
    # ),
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=True,
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
    typer.Option(
        "--sdk", help="Local Spaces search only. Filter by Space SDK. May be passed multiple times."
    ),
]
FilterOpt = Annotated[
    list[str] | None,
    typer.Option(
        "--filter",
        "-f",
        help="Local Spaces search only. Filter by Space tag. May be passed multiple times.",
    ),
]
TokenOpt = Annotated[
    str | None,
    typer.Option(
        "--token",
        help=(
            "Registry Bearer token. Also used as a Hugging Face token for local Spaces search "
            "or compatible hosted Spaces registries."
        ),
    ),
]
RegistryUrlOpt = Annotated[
    str,
    typer.Option(
        "--registry-url",
        help=(
            "Agent Finder registry URL to query. May be a registry base URL or its /search "
            "endpoint. Defaults to the hosted hf-agentfinder deployment."
        ),
    ),
]
IncludeNonRunningOpt = Annotated[
    bool,
    typer.Option(
        "--include-non-running", help="Local Spaces search only. Include non-running Spaces."
    ),
]
LocalOpt = Annotated[
    bool,
    typer.Option(
        "--local",
        help="Search directly from this process instead of using an Agent Finder registry URL.",
    ),
]
JsonOpt = Annotated[bool, typer.Option("--json", help="Emit Agent Finder JSON response.")]
FederationOpt = Annotated[
    FederationMode,
    typer.Option(
        "--federation",
        case_sensitive=False,
        help=(
            "Agent Finder federation mode to send in SearchRequest: auto, referrals, or none. "
            "Use referrals to ask registries for registry referrals that a client can search next."
        ),
    ),
]
BaseUrlOpt = Annotated[
    str,
    typer.Option(
        "--base-url",
        help=(
            "Hidden compatibility option for local in-process search. Base URL used for "
            "generated skill URLs."
        ),
        hidden=True,
    ),
]
KindOpt = Annotated[
    SpaceResultKind,
    typer.Option(
        "--kind",
        case_sensitive=False,
        help=(
            "Result view: skill (AI skills: indexed Hugging Face Skills plus generated Space "
            "SKILL.md wrappers), space (raw Hugging Face Space descriptors), mcp (MCP server "
            "entries for Spaces tagged mcp-server), or all. The 'all' kind can return both "
            "skill and MCP entries for one Space."
        ),
    ),
]


@dataclass(frozen=True)
class RegistrySearchResult:
    response: SearchResponse
    raw_body: str


def _missing_field_locations(exc: ValidationError) -> list[str]:
    locations: list[str] = []
    for error in exc.errors():
        if error.get("type") != "missing":
            continue
        loc = error.get("loc")
        if isinstance(loc, tuple):
            locations.append(".".join(str(part) for part in loc))
    return locations


def _registry_response_error_message(exc: ValidationError) -> str:
    missing_locations = _missing_field_locations(exc)
    missing_summary = ", ".join(missing_locations[:ERROR_FIELD_PREVIEW_LIMIT])
    if len(missing_locations) > ERROR_FIELD_PREVIEW_LIMIT:
        missing_summary = f"{missing_summary}, ... ({len(missing_locations)} total)"

    if any(
        location.startswith("results.") and location.endswith(".type")
        for location in missing_locations
    ):
        return (
            "registry returned a response that is not an Agent Finder v0.5 SearchResponse: "
            f"missing required catalog field(s): {missing_summary}. "
            "Search results must be catalog entries and include `type` media types. "
            "This usually means the registry is still serving an older pre-v0.5 schema "
            "or the server process needs to be restarted/redeployed."
        )

    if missing_summary:
        return (
            "registry returned a response that is not an Agent Finder v0.5 SearchResponse: "
            f"missing required field(s): {missing_summary}."
        )

    return (
        "registry returned a response that is not an Agent Finder v0.5 SearchResponse: "
        f"{exc.error_count()} validation error(s)."
    )


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


def _artifact_type_for_kind(kind: SpaceResultKind) -> str | None:
    artifact_types: dict[SpaceResultKind, str | None] = {
        "all": None,
        "skill": AI_SKILL_MEDIA_TYPE,
        "mcp": MCP_SERVER_MEDIA_TYPE,
        "space": HF_SPACE_MEDIA_TYPE,
    }
    return artifact_types[kind]


def _filter_for_kind(kind: SpaceResultKind) -> dict[str, list[str]]:
    artifact_type = _artifact_type_for_kind(kind)
    if artifact_type is None:
        return {}
    return {"type": [artifact_type]}


def _registry_search(
    registry_url: str,
    query: str,
    *,
    limit: int,
    kind: SpaceResultKind = "all",
    federation: FederationMode = "auto",
    token: str | None = None,
) -> RegistrySearchResult:
    request_body = SearchRequest(
        query=SearchQuery(text=query, filter=_filter_for_kind(kind)),
        federation=federation,
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
    except ValidationError as exc:
        raise typer.BadParameter(
            _registry_response_error_message(exc),
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
    federation: FederationMode = "auto",
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


def _combined_search_response(
    query: str,
    *,
    limit: int,
    sdk: list[str] | None = None,
    filters: list[str] | None = None,
    include_non_running: bool = False,
    token: bool | str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    kind: SpaceResultKind = "all",
) -> SearchResponse:
    results: list[SearchResult] = []
    if kind in {"all", "skill"}:
        results.extend(search_hf_skills(query, limit=limit))
    results.extend(
        search_hf_spaces(
            query,
            limit=limit,
            sdk=sdk,
            filters=filters,
            include_non_running=include_non_running,
            token=token,
            base_url=base_url,
            kind=kind,
        )
    )
    results.sort(key=lambda result: result.score, reverse=True)
    return SearchResponse(results=results[:limit])


def _result_type(result: SearchResult) -> str:
    if result.type == AI_SKILL_MEDIA_TYPE:
        return "skill"
    if result.type == MCP_SERVER_MEDIA_TYPE:
        return "mcp"
    if result.type == HF_SPACE_MEDIA_TYPE:
        return "space"
    return result.type


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
    registry_url: RegistryUrlOpt = DEFAULT_REGISTRY_URL,
    local: LocalOpt = False,
    federation: FederationOpt = "auto",
    json_output: JsonOpt = False,
    base_url: BaseUrlOpt = DEFAULT_REGISTRY_URL,
    kind: KindOpt = "all",
) -> None:
    """Search a registry (default Hugging Face).

    By default, POSTs an Agent Finder SearchRequest to the hosted hf-agentfinder registry.
    Use --registry-url for any compatible registry, or --local for in-process combined
    Skills and Spaces search. With --json, the CLI prints the registry's raw SearchResponse
    bytes instead of a normalized/re-serialized model, so reading agents can inspect exact
    result, referral, url, data, type, and pageToken fields returned by the server.
    """
    if local:
        _ = federation
        response = _combined_search_response(
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
        title = "Hugging Face Skills and Spaces"
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
    """Start the Agent Finder server."""
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
    """Start Agent Finder test server with challenge fixtures."""
    uvicorn.run(create_challenge_app(), host=host, port=port)
