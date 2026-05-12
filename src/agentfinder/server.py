from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Protocol
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.openapi.models import Example
from fastapi.responses import PlainTextResponse
from starlette.concurrency import run_in_threadpool

from agentfinder.hf_spaces import (
    AI_SKILL_MEDIA_TYPE,
    HF_SPACE_MEDIA_TYPE,
    LEGACY_HF_SPACE_MEDIA_TYPE,
    MCP_SERVER_MEDIA_TYPE,
    SpaceResultKind,
    build_space_skill_markdown,
    hf_space_agents_md_url,
    search_hf_spaces,
)
from agentfinder.models import SearchRequest, SearchResponse, SearchResult

if TYPE_CHECKING:
    from collections.abc import Mapping

SPACE_MEDIA_TYPES = {HF_SPACE_MEDIA_TYPE, LEGACY_HF_SPACE_MEDIA_TYPE}
BEARER_PREFIX = "Bearer "
SEARCH_REQUEST_EXAMPLES: dict[str, Example] = {
    "skill": Example(
        summary="Generated AI skill results",
        description="Return Hugging Face Spaces as generated `application/ai-skill` entries.",
        value={
            "query": {
                "text": "remove background from image",
                "mediaType": "application/ai-skill",
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
                "mediaType": "application/vnd.huggingface.space+json",
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
                "mediaType": "application/mcp-server+json",
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
        base_url: str = "http://127.0.0.1:8080",
    ) -> list[SearchResult]: ...


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _result_kind(media_type: str | None) -> SpaceResultKind | None:
    kinds: dict[str | None, SpaceResultKind] = {
        None: "all",
        AI_SKILL_MEDIA_TYPE: "skill",
        HF_SPACE_MEDIA_TYPE: "space",
        LEGACY_HF_SPACE_MEDIA_TYPE: "space",
        MCP_SERVER_MEDIA_TYPE: "mcp",
    }
    return kinds.get(media_type)


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
    base_url: str = "http://127.0.0.1:8080",
    include_non_running: bool = False,
    token: bool | str | None = None,
    search_spaces: SearchSpaces = search_hf_spaces,
) -> SearchResponse:
    kind = _result_kind(request.query.mediaType)
    if kind is None:
        return SearchResponse(results=[])

    return SearchResponse(
        results=search_spaces(
            request.query.text,
            limit=request.pageSize,
            include_non_running=include_non_running,
            token=token,
            kind=kind,
            base_url=base_url,
        )
    )


def fetch_agents_md(space_id: str) -> str:
    url = hf_space_agents_md_url(space_id)
    request = UrlRequest(url, headers={"User-Agent": "agentfinder/0.1"})  # noqa: S310 - public HF URL
    with urlopen(request, timeout=30) as response:  # noqa: S310 - public HF URL
        return response.read().decode("utf-8")


def create_app(
    *,
    include_non_running: bool = False,
    token: bool | str | None = None,
    search_spaces: SearchSpaces = search_hf_spaces,
) -> FastAPI:
    app = FastAPI(title="Hugging Face Spaces Agent Finder")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/search",
        response_model=SearchResponse,
        response_model_exclude_none=True,
        response_model_exclude_defaults=True,
        summary="Search Hugging Face Spaces",
        description=(
            "Search Hugging Face Spaces through the Agent Finder search envelope. Optional "
            "request-scoped Hugging Face tokens may be supplied with `X-HF-Authorization`, "
            "`Authorization`, or `HF_TOKEN` headers; they are used only for the downstream "
            "Spaces search request."
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
        return search_agent_finder(
            request_body,
            base_url=_base_url(request),
            include_non_running=include_non_running,
            token=effective_hf_token(
                request_token=hf_token_from_headers(request.headers),
                configured_token=token,
            ),
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
