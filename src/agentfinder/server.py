from __future__ import annotations

import os
from typing import TYPE_CHECKING, Annotated, Any, Protocol
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.openapi.models import Example
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool

from agentfinder.hf_skills import search_hf_skills
from agentfinder.hf_spaces import (
    AI_SKILL_MEDIA_TYPE,
    HF_SPACE_MEDIA_TYPE,
    MCP_SERVER_MEDIA_TYPE,
    SPACES_URL_PREFIX,
    SpaceResultKind,
    build_space_skill_markdown,
    hf_space_agents_md_url,
    search_hf_spaces,
)
from agentfinder.models import CatalogEntry, SearchRequest, SearchResponse, SearchResult

if TYPE_CHECKING:
    from collections.abc import Mapping

BEARER_PREFIX = "Bearer "
AI_CATALOG_MEDIA_TYPE = "application/ai-catalog+json"
AI_REGISTRY_MEDIA_TYPE = "application/ai-registry+json"
PUBLIC_BASE_URL_ENV = "AGENTFINDER_PUBLIC_BASE_URL"
URN_AI_PUBLISHER_PARTS = 3
SEARCH_REQUEST_EXAMPLES: dict[str, Example] = {
    "skill": Example(
        summary="Generated AI skill results",
        description="Return Hugging Face Spaces as generated `application/ai-skill` entries.",
        value={
            "query": {
                "text": "remove background from image",
                "filter": {"type": ["application/ai-skill"]},
            },
            "pageSize": 5,
        },
    ),
    "huggingface-space": Example(
        summary="Raw Hugging Face Space descriptors",
        description=(
            "Return matching Spaces as `application/vnd.huggingface.space+json` entries with "
            "inline Space metadata."
        ),
        value={
            "query": {
                "text": "generate images with flux",
                "filter": {"type": ["application/vnd.huggingface.space+json"]},
            },
            "pageSize": 5,
        },
    ),
    "mcp": Example(
        summary="MCP server discovery request",
        description=(
            "`application/mcp-server+json` returns MCP server entries for Hugging Face Spaces "
            "tagged `mcp-server`. The Hub search request is constrained with "
            "`filter=mcp-server&agents=true`."
        ),
        value={
            "query": {
                "text": "image generation mcp server",
                "filter": {"type": ["application/mcp-server+json"]},
            },
            "pageSize": 5,
        },
    ),
}


class SearchSpaces(Protocol):
    def __call__(
        self,
        query: str,
        *,
        limit: int = 10,
        include_non_running: bool = False,
        token: bool | str | None = None,
        kind: SpaceResultKind = "skill",
        base_url: str = SPACES_URL_PREFIX,
    ) -> list[SearchResult]: ...


class SearchSkills(Protocol):
    def __call__(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[SearchResult]: ...


def _base_url(request: Request) -> str:
    configured = os.environ.get(PUBLIC_BASE_URL_ENV)
    if configured is not None:
        stripped = configured.strip().rstrip("/")
        if stripped:
            return stripped
    return str(request.base_url).rstrip("/")


def _spaces_registry_search_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/registries/huggingface/spaces/search"


def _spaces_registry_referral(base_url: str) -> CatalogEntry:
    return CatalogEntry(
        identifier="urn:ai:hf.co:registry:spaces",
        displayName="Hugging Face Spaces Registry",
        type=AI_REGISTRY_MEDIA_TYPE,
        url=_spaces_registry_search_url(base_url),
        description=(
            "Search generated skills, Space descriptors, and MCP entries from running "
            "Hugging Face Spaces."
        ),
        tags=["huggingface", "spaces", "registry"],
        metadata={"path": "/registries/huggingface/spaces/search"},
    )


def _registry_catalog_entry(base_url: str) -> CatalogEntry:
    return CatalogEntry(
        identifier="urn:ai:hf.co:registry:agentfinder",
        displayName="Hugging Face Agent Finder Registry",
        type=AI_REGISTRY_MEDIA_TYPE,
        url=f"{base_url.rstrip('/')}/search",
        description="Search indexed Hugging Face Skills and running Hugging Face Spaces.",
        tags=["huggingface", "registry", "search"],
        metadata={"path": "/search"},
    )


def _catalog_payload(base_url: str) -> dict[str, object]:
    return {
        "specVersion": "1.0",
        "host": {
            "displayName": "Hugging Face Agent Finder",
            "identifier": "hf.co",
            "documentationUrl": "https://github.com/huggingface/hf-agentfinder",
        },
        "entries": [
            _registry_catalog_entry(base_url).model_dump(
                exclude_none=True,
                exclude_defaults=True,
            ),
            _spaces_registry_referral(base_url).model_dump(
                exclude_none=True,
                exclude_defaults=True,
            ),
        ],
    }


def _skills_configured(search_skills: SearchSkills) -> bool:
    return search_skills is not search_hf_skills or bool(os.environ.get("AGENTFINDER_MEILI_URL"))


def _health_payload(search_skills: SearchSkills) -> dict[str, object]:
    return {
        "status": "ok",
        "registries": {
            "huggingface": {
                "configured": _skills_configured(search_skills),
                "path": "/search",
                "description": "Combined Hugging Face Skills and Spaces search.",
            },
            "huggingface/skills": {
                "configured": _skills_configured(search_skills),
                "path": "/search",
                "description": "Included in the combined root registry.",
            },
            "huggingface/spaces": {
                "configured": True,
                "path": "/registries/huggingface/spaces/search",
                "description": "Targeted Spaces-only nested registry.",
            },
        },
    }


def _result_kind(artifact_type: str) -> SpaceResultKind | None:
    kinds: dict[str, SpaceResultKind] = {
        AI_SKILL_MEDIA_TYPE: "skill",
        HF_SPACE_MEDIA_TYPE: "space",
        MCP_SERVER_MEDIA_TYPE: "mcp",
    }
    return kinds.get(artifact_type)


def _filter_values(raw_filter: dict[str, Any], field: str) -> list[Any]:
    if field not in raw_filter:
        return []
    value = raw_filter[field]
    if isinstance(value, list):
        return value
    return [value]


def _type_filters(request: SearchRequest) -> list[str]:
    return [
        value for value in _filter_values(request.query.filter, "type") if isinstance(value, str)
    ]


def _space_kinds_for_types(artifact_types: list[str]) -> list[SpaceResultKind]:
    if not artifact_types:
        return ["all"]

    kinds: list[SpaceResultKind] = []
    for artifact_type in artifact_types:
        kind = _result_kind(artifact_type)
        if kind is not None and kind not in kinds:
            kinds.append(kind)
    return kinds


def _includes_skill_index(artifact_types: list[str]) -> bool:
    return not artifact_types or AI_SKILL_MEDIA_TYPE in artifact_types


def _publisher_from_identifier(identifier: str) -> str | None:
    parts = identifier.split(":")
    if len(parts) >= URN_AI_PUBLISHER_PARTS and parts[0] == "urn" and parts[1] == "ai":
        return parts[2]
    return None


def _entry_values_at_path(value: Any, path: list[str]) -> list[Any]:
    if not path:
        return value if isinstance(value, list) else [value]
    if isinstance(value, list):
        return [item for child in value for item in _entry_values_at_path(child, path)]
    if not isinstance(value, dict):
        return []
    current = value.get(path[0])
    return [] if current is None else _entry_values_at_path(current, path[1:])


def _entry_filter_values(entry: SearchResult, field: str) -> list[Any]:
    if field == "publisher":
        publisher = _publisher_from_identifier(entry.identifier)
        return [] if publisher is None else [publisher]

    payload = entry.model_dump(exclude_none=True)
    return _entry_values_at_path(payload, field.split("."))


def _matches_filter(entry: SearchResult, raw_filter: dict[str, Any]) -> bool:
    for field, expected in raw_filter.items():
        expected_values = expected if isinstance(expected, list) else [expected]
        actual_values = _entry_filter_values(entry, field)
        if not any(
            actual == expected_value
            for actual in actual_values
            for expected_value in expected_values
        ):
            return False
    return True


def _apply_entry_filters(results: list[SearchResult], request: SearchRequest) -> list[SearchResult]:
    if not request.query.filter:
        return results
    return [result for result in results if _matches_filter(result, request.query.filter)]


def _bearer_token(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.startswith(BEARER_PREFIX):
        return None
    token = value[len(BEARER_PREFIX) :].strip()
    return token or None


def hf_token_from_headers(headers: Mapping[str, str]) -> str | None:
    """Return a request-scoped HF token from supported headers, in precedence order."""
    x_hf_authorization = _bearer_token(headers.get("X-HF-Authorization"))
    if x_hf_authorization is not None:
        return x_hf_authorization

    authorization = _bearer_token(headers.get("Authorization"))
    if authorization is not None:
        return authorization

    hf_token = headers.get("HF_TOKEN")
    if hf_token is None:
        return None
    token = hf_token.strip()
    return token or None


def effective_hf_token(
    *,
    request_token: str | None,
    configured_token: bool | str | None,
) -> bool | str | None:
    return request_token or configured_token


def search_agent_finder(
    request: SearchRequest,
    *,
    base_url: str = SPACES_URL_PREFIX,
    include_non_running: bool = False,
    token: bool | str | None = None,
    search_skills: SearchSkills = search_hf_skills,
    search_spaces: SearchSpaces = search_hf_spaces,
) -> SearchResponse:
    results: list[SearchResult] = []
    artifact_types = _type_filters(request)
    space_kinds = _space_kinds_for_types(artifact_types)
    if artifact_types and not space_kinds and not _includes_skill_index(artifact_types):
        return SearchResponse(results=[])

    if _includes_skill_index(artifact_types):
        results.extend(search_skills(request.query.text, limit=request.pageSize))
    for kind in space_kinds:
        results.extend(
            search_spaces(
                request.query.text,
                limit=request.pageSize,
                include_non_running=include_non_running,
                token=token,
                kind=kind,
                base_url=base_url,
            )
        )
    results = _apply_entry_filters(results, request)
    results.sort(key=lambda result: result.score, reverse=True)

    referrals = []
    if request.federation in {"auto", "referrals"}:
        referrals.append(_spaces_registry_referral(base_url))

    return SearchResponse(results=results[: request.pageSize], referrals=referrals)


def search_spaces_agent_finder(
    request: SearchRequest,
    *,
    base_url: str = SPACES_URL_PREFIX,
    include_non_running: bool = False,
    token: bool | str | None = None,
    search_spaces: SearchSpaces = search_hf_spaces,
) -> SearchResponse:
    artifact_types = _type_filters(request)
    space_kinds = _space_kinds_for_types(artifact_types)
    if not space_kinds:
        return SearchResponse(results=[])

    results: list[SearchResult] = []
    for kind in space_kinds:
        results.extend(
            search_spaces(
                request.query.text,
                limit=request.pageSize,
                include_non_running=include_non_running,
                token=token,
                kind=kind,
                base_url=base_url,
            )
        )
    results = _apply_entry_filters(results, request)
    results.sort(key=lambda result: result.score, reverse=True)
    return SearchResponse(results=results[: request.pageSize])


def fetch_agents_md(space_id: str) -> str:
    url = hf_space_agents_md_url(space_id)
    request = UrlRequest(url, headers={"User-Agent": "agentfinder/0.1"})  # noqa: S310 - public HF URL
    with urlopen(request, timeout=30) as response:  # noqa: S310 - public HF URL
        return response.read().decode("utf-8")


def _add_spaces_search_route(
    app: FastAPI,
    *,
    include_non_running: bool,
    token: bool | str | None,
    search_spaces: SearchSpaces,
) -> None:
    @app.post(
        "/registries/huggingface/spaces/search",
        response_model=SearchResponse,
        response_model_exclude_none=True,
        response_model_exclude_defaults=True,
        summary="Search Hugging Face Spaces",
        description=(
            "Search running Hugging Face Spaces through the Agent Finder search envelope. "
            "Optional request-scoped Hugging Face tokens may be supplied with "
            "`X-HF-Authorization`, `Authorization`, or `HF_TOKEN` headers; they are used only "
            "for the downstream Spaces search request."
        ),
    )
    async def spaces_search(
        request_body: Annotated[SearchRequest, Body(openapi_examples=SEARCH_REQUEST_EXAMPLES)],
        request: Request,
        x_hf_authorization: Annotated[
            str | None,
            Header(
                alias="X-HF-Authorization",
                description=(
                    "Optional request-scoped Hugging Face token. Use `Bearer hf_...`. "
                    "Highest precedence."
                ),
            ),
        ] = None,
        authorization: Annotated[
            str | None,
            Header(
                alias="Authorization",
                description=(
                    "Optional request-scoped Hugging Face token. Use `Bearer hf_...`. "
                    "Used when `X-HF-Authorization` is absent."
                ),
            ),
        ] = None,
        hf_token: Annotated[
            str | None,
            Header(
                alias="HF_TOKEN",
                description=(
                    "Optional request-scoped Hugging Face token without a Bearer prefix. "
                    "Used when authorization headers are absent."
                ),
            ),
        ] = None,
    ) -> SearchResponse:
        _ = x_hf_authorization, authorization, hf_token
        return search_spaces_agent_finder(
            request_body,
            base_url=_base_url(request),
            include_non_running=include_non_running,
            token=effective_hf_token(
                request_token=hf_token_from_headers(request.headers),
                configured_token=token,
            ),
            search_spaces=search_spaces,
        )


def _add_catalog_route(app: FastAPI) -> None:
    @app.get(
        "/.well-known/ai-catalog.json",
        response_class=JSONResponse,
        summary="AI Catalog discovery document",
        description=(
            "Return an Agent Finder v0.5-compatible AI Catalog advertising the primary "
            "Hugging Face Agent Finder registry and nested Spaces registry."
        ),
    )
    async def well_known_ai_catalog(request: Request) -> JSONResponse:
        return JSONResponse(
            _catalog_payload(_base_url(request)),
            media_type=AI_CATALOG_MEDIA_TYPE,
        )


def create_app(
    *,
    include_non_running: bool = False,
    token: bool | str | None = None,
    search_skills: SearchSkills = search_hf_skills,
    search_spaces: SearchSpaces = search_hf_spaces,
) -> FastAPI:
    app = FastAPI(title="Hugging Face Agent Finder")

    @app.get("/health")
    async def health() -> dict[str, object]:
        return _health_payload(search_skills)

    _add_catalog_route(app)

    @app.post(
        "/search",
        response_model=SearchResponse,
        response_model_exclude_none=True,
        response_model_exclude_defaults=True,
        summary="Search Hugging Face Skills and Spaces",
        description=(
            "Search indexed Hugging Face Skills and running Hugging Face Spaces through one "
            "Agent Finder search envelope. The nested Spaces registry remains available for "
            "clients that want targeted Spaces-only search or explicit federation traversal."
        ),
    )
    async def search(
        request_body: Annotated[SearchRequest, Body(openapi_examples=SEARCH_REQUEST_EXAMPLES)],
        request: Request,
        x_hf_authorization: Annotated[
            str | None,
            Header(
                alias="X-HF-Authorization",
                description=(
                    "Optional request-scoped Hugging Face token for the Spaces portion of "
                    "combined search. Use `Bearer hf_...`. Highest precedence."
                ),
            ),
        ] = None,
        authorization: Annotated[
            str | None,
            Header(
                alias="Authorization",
                description=(
                    "Optional request-scoped Hugging Face token for the Spaces portion of "
                    "combined search. Use `Bearer hf_...`. Used when `X-HF-Authorization` is "
                    "absent."
                ),
            ),
        ] = None,
        hf_token: Annotated[
            str | None,
            Header(
                alias="HF_TOKEN",
                description=(
                    "Optional request-scoped Hugging Face token without a Bearer prefix for "
                    "the Spaces portion of combined search. Used when authorization headers "
                    "are absent."
                ),
            ),
        ] = None,
    ) -> SearchResponse:
        _ = x_hf_authorization, authorization, hf_token
        return search_agent_finder(
            request_body,
            base_url=_base_url(request),
            include_non_running=include_non_running,
            token=effective_hf_token(
                request_token=hf_token_from_headers(request.headers),
                configured_token=token,
            ),
            search_skills=search_skills,
            search_spaces=search_spaces,
        )

    _add_spaces_search_route(
        app,
        include_non_running=include_non_running,
        token=token,
        search_spaces=search_spaces,
    )

    @app.get(
        "/skills/huggingface/{owner}/{space_name}/SKILL.md",
        response_class=PlainTextResponse,
    )
    async def hf_space_skill(owner: str, space_name: str) -> PlainTextResponse:
        space_id = f"{owner}/{space_name}"
        try:
            agents_md = await run_in_threadpool(fetch_agents_md, space_id)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch Hugging Face Space agents.md: {exc}",
            ) from exc

        return PlainTextResponse(
            build_space_skill_markdown(space_id=space_id, agents_md=agents_md),
            media_type="text/markdown; charset=utf-8",
        )

    @app.get(
        "/spaces/huggingface/{owner}/{space_name}/agents.md",
        response_class=PlainTextResponse,
    )
    async def hf_space_agents_md(owner: str, space_name: str) -> PlainTextResponse:
        space_id = f"{owner}/{space_name}"
        try:
            agents_md = await run_in_threadpool(fetch_agents_md, space_id)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch Hugging Face Space agents.md: {exc}",
            ) from exc
        return PlainTextResponse(agents_md, media_type="text/markdown; charset=utf-8")

    return app
