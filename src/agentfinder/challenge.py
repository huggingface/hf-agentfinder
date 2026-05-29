from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from agentfinder.hf_spaces import AI_SKILL_MEDIA_TYPE, MCP_SERVER_MEDIA_TYPE
from agentfinder.models import CatalogEntry, SearchRequest, SearchResponse, SearchResult

A2A_AGENT_MEDIA_TYPE = "application/a2a-agent-card+json"
AI_CATALOG_MEDIA_TYPE = "application/ai-catalog+json"
AI_REGISTRY_MEDIA_TYPE = "application/ai-registry+json"
CHALLENGE_SOURCE = "agentfinder:challenge"
CHALLENGE_PUBLISHER = "agentfinder.dev"


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _score(entry: SearchResult, query: str, index: int) -> float:
    haystack = " ".join(
        [
            entry.displayName,
            entry.description or "",
            " ".join(entry.tags),
            " ".join(entry.capabilities),
        ]
    ).lower()
    terms = [term for term in query.lower().split() if term]
    matches = sum(1 for term in terms if term in haystack)
    return max(1.0, entry.score + matches * 5 - index)


def _skill_result(base_url: str, name: str, description: str, score: float) -> SearchResult:
    return SearchResult(
        identifier=f"urn:ai:{CHALLENGE_PUBLISHER}:challenge:skill:{name}",
        displayName=name,
        type=AI_SKILL_MEDIA_TYPE,
        url=f"{base_url}/artifacts/skills/{name}/SKILL.md",
        description=description,
        tags=["challenge", "skill", "markdown"],
        capabilities=["instructions", "workflow"],
        metadata={"sourceType": "challenge-skill", "registryPath": "/search"},
        score=score,
        source=CHALLENGE_SOURCE,
    )


def _mcp_result(base_url: str, name: str, description: str, score: float) -> SearchResult:
    return SearchResult(
        identifier=f"urn:ai:{CHALLENGE_PUBLISHER}:challenge:mcp:{name}",
        displayName=f"{name} MCP Server",
        type=MCP_SERVER_MEDIA_TYPE,
        data={
            "name": name,
            "transport": "http",
            "url": f"{base_url}/artifacts/mcp/{name}",
            "tools": [
                {
                    "name": "challenge_echo",
                    "description": "Echo input for client integration tests.",
                    "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
                }
            ],
        },
        description=description,
        tags=["challenge", "mcp", "tool-server"],
        capabilities=["challenge_echo"],
        metadata={"sourceType": "challenge-mcp", "registryPath": "/search"},
        score=score,
        source=CHALLENGE_SOURCE,
    )


def _a2a_result(name: str, description: str, score: float) -> SearchResult:
    return SearchResult(
        identifier=f"urn:ai:{CHALLENGE_PUBLISHER}:challenge:a2a:{name}",
        displayName=f"{name} A2A Agent",
        type=A2A_AGENT_MEDIA_TYPE,
        data={
            "name": name,
            "description": description,
            "url": f"https://challenge.invalid/a2a/{name}",
            "capabilities": {"streaming": True, "pushNotifications": False},
        },
        description=description,
        tags=["challenge", "a2a", "agent"],
        capabilities=["delegate_task"],
        metadata={"sourceType": "challenge-a2a", "registryPath": "/search"},
        score=score,
        source=CHALLENGE_SOURCE,
    )


def _catalog_result(base_url: str, score: float) -> SearchResult:
    return SearchResult(
        identifier=f"urn:ai:{CHALLENGE_PUBLISHER}:challenge:catalog:bundle",
        displayName="Challenge Bundle Catalog",
        type=AI_CATALOG_MEDIA_TYPE,
        data={
            "specVersion": "1.0",
            "host": {"displayName": "Challenge Bundle"},
            "entries": [
                {
                    "identifier": f"urn:ai:{CHALLENGE_PUBLISHER}:challenge:bundle:skill",
                    "displayName": "Bundled Skill",
                    "type": AI_SKILL_MEDIA_TYPE,
                    "url": f"{base_url}/artifacts/skills/bundled-skill/SKILL.md",
                },
                {
                    "identifier": f"urn:ai:{CHALLENGE_PUBLISHER}:challenge:bundle:mcp",
                    "displayName": "Bundled MCP",
                    "type": MCP_SERVER_MEDIA_TYPE,
                    "data": {"name": "bundled-mcp", "transport": "stdio", "command": "echo"},
                },
            ],
        },
        description="Nested ai-catalog bundle with mixed artifact entries.",
        tags=["challenge", "catalog", "bundle"],
        capabilities=["catalog_expansion"],
        metadata={"sourceType": "challenge-catalog", "registryPath": "/search"},
        score=score,
        source=CHALLENGE_SOURCE,
    )


def _registry_result(
    base_url: str,
    name: str,
    path: str,
    description: str,
    score: float,
) -> SearchResult:
    return SearchResult(
        identifier=f"urn:ai:{CHALLENGE_PUBLISHER}:challenge:registry:{name}",
        displayName=f"{name.title()} Challenge Registry",
        type=AI_REGISTRY_MEDIA_TYPE,
        url=f"{base_url}{path}",
        description=description,
        tags=["challenge", "registry", "sub-registry"],
        capabilities=["search"],
        metadata={"sourceType": "challenge-registry", "registryPath": path},
        score=score,
        source=CHALLENGE_SOURCE,
    )


def _referral(base_url: str, name: str, path: str, description: str) -> CatalogEntry:
    return CatalogEntry(
        identifier=f"urn:ai:{CHALLENGE_PUBLISHER}:challenge:registry:{name}",
        displayName=f"{name.title()} Challenge Registry",
        type=AI_REGISTRY_MEDIA_TYPE,
        url=f"{base_url}{path}",
        description=description,
        tags=["challenge", "registry", "referral"],
        metadata={"registryPath": path},
    )


def _root_results(base_url: str) -> list[SearchResult]:
    return [
        _skill_result(
            base_url,
            "triage-skill",
            "Classify issues, collect missing context, and propose next actions.",
            92,
        ),
        _mcp_result(
            base_url,
            "echo-tools",
            "Simple HTTP MCP server descriptor for testing tool discovery.",
            88,
        ),
        _a2a_result("planner", "Delegates multi-step planning work to an A2A agent.", 84),
        _catalog_result(base_url, 80),
        _registry_result(
            base_url,
            "tools",
            "/registries/tools/search",
            "Sub-registry containing MCP-heavy tool results.",
            76,
        ),
        _registry_result(
            base_url,
            "skills",
            "/registries/skills/search",
            "Sub-registry containing skill-heavy results.",
            74,
        ),
        _registry_result(
            base_url,
            "nested",
            "/registries/nested/search",
            "Sub-registry that refers to another deeper registry.",
            72,
        ),
        _registry_result(
            base_url,
            "empty",
            "/registries/empty/search",
            "Sub-registry that intentionally returns no results.",
            20,
        ),
    ]


def _tools_results(base_url: str) -> list[SearchResult]:
    return [
        _mcp_result(base_url, "filesystem-tools", "MCP server for file browsing tasks.", 95),
        _mcp_result(base_url, "ticket-tools", "MCP server for issue and ticket workflows.", 90),
        _skill_result(base_url, "tool-router", "Choose between available MCP servers.", 70),
    ]


def _skills_results(base_url: str) -> list[SearchResult]:
    return [
        _skill_result(base_url, "research-skill", "Research a topic and cite findings.", 96),
        _skill_result(base_url, "release-skill", "Prepare release notes and checklists.", 91),
        _a2a_result("reviewer", "Review plans and implementation diffs.", 67),
    ]


def _nested_results(base_url: str) -> list[SearchResult]:
    return [
        _registry_result(
            base_url,
            "deep",
            "/registries/deep/search",
            "Second-level registry with leaf artifacts.",
            91,
        ),
        _skill_result(
            base_url,
            "tree-walker",
            "Follow registry referrals until leaf artifacts.",
            83,
        ),
    ]


def _deep_results(base_url: str) -> list[SearchResult]:
    return [
        _mcp_result(base_url, "deep-mcp", "Leaf MCP server in a second-level registry.", 93),
        _skill_result(base_url, "deep-skill", "Leaf skill in a second-level registry.", 89),
    ]


def _filter_results(
    results: list[SearchResult],
    request: SearchRequest,
) -> list[SearchResult]:
    raw_type_filter = request.query.filter.get("type")
    type_filter = raw_type_filter if isinstance(raw_type_filter, list) else [raw_type_filter]
    filtered = [
        result for result in results if raw_type_filter is None or result.type in type_filter
    ]
    ranked = [
        result.model_copy(update={"score": _score(result, request.query.text, index)})
        for index, result in enumerate(filtered)
    ]
    ranked.sort(key=lambda result: result.score, reverse=True)
    return ranked[: request.pageSize]


def _search_response(
    request: SearchRequest,
    *,
    base_url: str,
    results: list[SearchResult],
    referrals: list[CatalogEntry] | None = None,
) -> SearchResponse:
    response_referrals = referrals or []
    if request.federation in {"auto", "referrals"} and not response_referrals:
        response_referrals = [
            _referral(
                base_url,
                "tools",
                "/registries/tools/search",
                "Sub-registry containing MCP-heavy tool results.",
            ),
            _referral(
                base_url,
                "skills",
                "/registries/skills/search",
                "Sub-registry containing skill-heavy results.",
            ),
            _referral(
                base_url,
                "nested",
                "/registries/nested/search",
                "Sub-registry that refers to another deeper registry.",
            ),
        ]
    return SearchResponse(
        results=_filter_results(results, request),
        referrals=response_referrals,
    )


def _catalog(base_url: str) -> dict[str, Any]:
    return {
        "specVersion": "1.0",
        "host": {
            "displayName": "Agent Finder Challenge Registry",
            "documentationUrl": f"{base_url}/docs",
        },
        "entries": [
            result.model_dump(exclude={"score", "source"}, exclude_none=True)
            for result in _root_results(base_url)
        ],
    }


def _add_health_routes(app: FastAPI) -> None:
    @app.get("/health")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "mode": "challenge",
            "registries": {
                "root": {"path": "/search"},
                "tools": {"path": "/registries/tools/search"},
                "skills": {"path": "/registries/skills/search"},
                "nested": {"path": "/registries/nested/search"},
                "deep": {"path": "/registries/deep/search"},
                "empty": {"path": "/registries/empty/search"},
            },
        }


def _add_catalog_routes(app: FastAPI) -> None:
    @app.get("/.well-known/ai-catalog.json")
    async def well_known_catalog(request: Request) -> dict[str, Any]:
        return _catalog(_base_url(request))


def _add_search_routes(app: FastAPI) -> None:
    @app.post("/search", response_model=SearchResponse, response_model_exclude_none=True)
    async def search(
        request_body: SearchRequest,
        request: Request,
    ) -> SearchResponse:
        return _search_response(
            request_body,
            base_url=_base_url(request),
            results=_root_results(_base_url(request)),
        )

    @app.post(
        "/registries/tools/search",
        response_model=SearchResponse,
        response_model_exclude_none=True,
    )
    async def search_tools(request_body: SearchRequest, request: Request) -> SearchResponse:
        return _search_response(
            request_body,
            base_url=_base_url(request),
            results=_tools_results(_base_url(request)),
        )

    @app.post(
        "/registries/skills/search",
        response_model=SearchResponse,
        response_model_exclude_none=True,
    )
    async def search_skills(request_body: SearchRequest, request: Request) -> SearchResponse:
        return _search_response(
            request_body,
            base_url=_base_url(request),
            results=_skills_results(_base_url(request)),
        )

    @app.post(
        "/registries/nested/search",
        response_model=SearchResponse,
        response_model_exclude_none=True,
    )
    async def search_nested(request_body: SearchRequest, request: Request) -> SearchResponse:
        base_url = _base_url(request)
        return _search_response(
            request_body,
            base_url=base_url,
            results=_nested_results(base_url),
            referrals=[
                _referral(
                    base_url,
                    "deep",
                    "/registries/deep/search",
                    "Second-level registry with leaf artifacts.",
                )
            ],
        )

    @app.post(
        "/registries/deep/search",
        response_model=SearchResponse,
        response_model_exclude_none=True,
    )
    async def search_deep(request_body: SearchRequest, request: Request) -> SearchResponse:
        return _search_response(
            request_body,
            base_url=_base_url(request),
            results=_deep_results(_base_url(request)),
        )

    @app.post(
        "/registries/empty/search",
        response_model=SearchResponse,
        response_model_exclude_none=True,
    )
    async def search_empty(request_body: SearchRequest, request: Request) -> SearchResponse:
        return _search_response(request_body, base_url=_base_url(request), results=[])


def _add_artifact_routes(app: FastAPI) -> None:
    @app.get("/artifacts/skills/{name}/SKILL.md", response_class=PlainTextResponse)
    async def skill_artifact(name: str) -> PlainTextResponse:
        body = f"""---
name: "{name}"
description: "Challenge fixture skill for Agent Finder client testing."
---

# {name}

Use this fixture to test fetching skill artifacts from search results.
"""
        return PlainTextResponse(body, media_type="text/markdown; charset=utf-8")

    @app.get("/artifacts/mcp/{name}")
    async def mcp_artifact(name: str, request: Request) -> dict[str, Any]:
        return {
            "name": name,
            "transport": "http",
            "url": f"{_base_url(request)}/artifacts/mcp/{name}",
            "tools": [{"name": "challenge_echo", "description": "Echo test input."}],
        }


def create_challenge_app() -> FastAPI:
    app = FastAPI(title="Agent Finder Challenge Registry")
    _add_health_routes(app)
    _add_catalog_routes(app)
    _add_search_routes(app)
    _add_artifact_routes(app)
    return app
