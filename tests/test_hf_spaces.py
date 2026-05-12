from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import TYPE_CHECKING, cast
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from agentfinder import cli, server
from agentfinder.hf_search import HfSemanticSpaceSearcher

if TYPE_CHECKING:
    from collections.abc import Iterable

from agentfinder.hf_spaces import (
    AI_SKILL_MEDIA_TYPE,
    HF_SPACE_MEDIA_TYPE,
    MCP_SERVER_MEDIA_TYPE,
    SpaceResultKind,
    SpaceSearcher,
    SpaceSearchResultLike,
    build_space_skill_markdown,
    hf_space_agents_md_url,
    hf_space_app_url,
    hf_space_mcp_sse_url,
    search_hf_spaces,
    space_to_search_result,
)
from agentfinder.models import SearchQuery, SearchRequest, SearchResult
from agentfinder.server import (
    create_app,
    effective_hf_token,
    hf_token_from_headers,
    search_agent_finder,
)

SEARCH_BODY = {
    "query": {"text": "image editing", "mediaType": "application/ai-skill"},
    "pageSize": 5,
}
SEARCH_RESPONSE = b"""[
  {
    "id": "alice/mcp",
    "author": "alice",
    "title": "MCP Space",
    "sdk": "gradio",
    "likes": 1,
    "private": false,
    "tags": ["gradio", "mcp-server"],
    "runtime": {"stage": "RUNNING"},
    "ai_short_description": "Use an MCP Space.",
    "ai_category": "Agents",
    "semanticRelevancyScore": 0.5,
    "trendingScore": 2
  }
]"""


class SearchRequestRecorder:
    path: str | None = None
    authorization: str | None = None


class SearchHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        SearchRequestRecorder.path = self.path
        SearchRequestRecorder.authorization = self.headers.get("Authorization")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(SEARCH_RESPONSE)

    def log_message(self, format: str, *args: object) -> None:
        return


@dataclass
class Runtime:
    stage: str | None


@dataclass
class Space:
    id: str
    author: str = "alice"
    title: str = "Image Tool"
    emoji: str | None = "🎨"
    sdk: str | None = "gradio"
    likes: int = 12
    private: bool = False
    tags: list[str] | None = None
    runtime: Runtime | None = None
    ai_short_description: str | None = "Generate and edit images."
    ai_category: str | None = "Image Editing"
    semantic_relevancy_score: float | None = 0.91
    trending_score: int | None = 7


class Searcher:
    def __init__(self, spaces: list[Space]) -> None:
        self.spaces = spaces
        self.filters: list[str | Iterable[str] | None] = []
        self.agents: list[bool] = []

    def search_spaces(
        self,
        query: str,
        *,
        filter: str | Iterable[str] | None = None,
        sdk: str | list[str] | None = None,
        include_non_running: bool = False,
        token: bool | str | None = None,
        agents: bool = True,
    ) -> Iterable[SpaceSearchResultLike]:
        self.filters.append(filter)
        self.agents.append(agents)
        return iter(cast("list[SpaceSearchResultLike]", self.spaces))


class RecordingSearch:
    def __init__(self) -> None:
        self.tokens: list[bool | str | None] = []

    def __call__(
        self,
        query: str,
        *,
        limit: int = 10,
        include_non_running: bool = False,
        token: bool | str | None = None,
        kind: SpaceResultKind = "skill",
        base_url: str = "http://127.0.0.1:8080",
    ) -> list[SearchResult]:
        self.tokens.append(token)
        return []


def test_space_to_search_result_defaults_to_skill_wrapper() -> None:
    space = Space(id="alice/cool.space", tags=["image-to-image"], runtime=Runtime(stage="RUNNING"))
    result = space_to_search_result(cast("SpaceSearchResultLike", space))

    assert result.identifier == "urn:huggingface:skill:space:alice:cool.space"
    assert result.displayName == "Image Tool"
    assert result.mediaType == AI_SKILL_MEDIA_TYPE
    assert result.url == "http://127.0.0.1:8080/skills/huggingface/alice/cool.space/SKILL.md"
    assert result.description == "Generate and edit images."
    assert result.score == 91.0
    assert result.source == "https://huggingface.co"
    assert result.metadata["spaceId"] == "alice/cool.space"
    assert result.metadata["runtimeStage"] == "RUNNING"
    assert (
        result.metadata["agentsMdUrl"]
        == "https://huggingface.co/spaces/alice/cool.space/resolve/main/agents.md"
    )
    assert "image-to-image" in result.tags


def test_space_to_search_result_can_return_generic_space_descriptor() -> None:
    space = Space(id="alice/cool.space")
    result = space_to_search_result(cast("SpaceSearchResultLike", space), kind="space")

    assert result.identifier == "urn:huggingface:space:alice:cool.space"
    assert result.mediaType == HF_SPACE_MEDIA_TYPE
    assert result.url is None
    assert result.data is not None
    assert result.data["spaceId"] == "alice/cool.space"
    assert result.data["hubUrl"] == "https://huggingface.co/spaces/alice/cool.space"


def test_hf_space_app_url_is_best_effort_hf_space_subdomain() -> None:
    assert hf_space_app_url("Alice/Cool.Space") == "https://alice-cool-space.hf.space"


def test_hf_space_mcp_sse_url_uses_gradio_mcp_endpoint() -> None:
    assert (
        hf_space_mcp_sse_url("Alice/Cool.Space")
        == "https://alice-cool-space.hf.space/gradio_api/mcp/sse"
    )


def test_hf_space_agents_md_url_uses_raw_resolve_path() -> None:
    assert (
        hf_space_agents_md_url("alice/cool.space")
        == "https://huggingface.co/spaces/alice/cool.space/resolve/main/agents.md"
    )


def test_search_hf_spaces_uses_supplied_searcher_and_limit() -> None:
    searcher = Searcher(
        [
            Space(id="alice/one", runtime=Runtime(stage="RUNNING")),
            Space(id="alice/two", runtime=Runtime(stage="RUNNING")),
        ]
    )
    results = search_hf_spaces("image editing", limit=1, searcher=cast("SpaceSearcher", searcher))

    assert [result.metadata["spaceId"] for result in results] == ["alice/one"]


def test_search_hf_spaces_only_returns_running_spaces() -> None:
    searcher = Searcher(
        [
            Space(id="alice/building", runtime=Runtime(stage="BUILDING")),
            Space(id="alice/running", runtime=Runtime(stage="RUNNING")),
            Space(id="alice/unknown"),
            Space(id="alice/stopped", runtime=Runtime(stage="STOPPED")),
            Space(id="alice/running-two", runtime=Runtime(stage="RUNNING")),
        ]
    )
    results = search_hf_spaces(
        "image editing",
        limit=2,
        include_non_running=True,
        searcher=cast("SpaceSearcher", searcher),
    )

    assert [result.metadata["spaceId"] for result in results] == [
        "alice/running",
        "alice/running-two",
    ]


def test_search_hf_spaces_requests_agent_spaces_by_default() -> None:
    searcher = Searcher([Space(id="alice/one", runtime=Runtime(stage="RUNNING"))])

    search_hf_spaces("image editing", searcher=cast("SpaceSearcher", searcher))

    assert searcher.agents == [True]


def test_search_hf_spaces_adds_mcp_filter_for_mcp_results() -> None:
    searcher = Searcher(
        [Space(id="alice/mcp", tags=["mcp-server"], runtime=Runtime(stage="RUNNING"))]
    )
    results = search_hf_spaces(
        "image editing",
        searcher=cast("SpaceSearcher", searcher),
        kind="mcp",
    )

    assert searcher.filters == [["mcp-server"]]
    assert [result.mediaType for result in results] == [MCP_SERVER_MEDIA_TYPE]
    assert results[0].data == {
        "name": "hf-space-alice-mcp",
        "transport": "sse",
        "url": "https://alice-mcp.hf.space/gradio_api/mcp/sse",
    }


def test_search_hf_spaces_returns_skill_and_mcp_for_unfiltered_search() -> None:
    searcher = Searcher(
        [Space(id="alice/mcp", tags=["mcp-server"], runtime=Runtime(stage="RUNNING"))]
    )

    results = search_hf_spaces(
        "image editing",
        limit=2,
        searcher=cast("SpaceSearcher", searcher),
        kind="all",
    )

    assert [result.mediaType for result in results] == [AI_SKILL_MEDIA_TYPE, MCP_SERVER_MEDIA_TYPE]


def test_cli_search_response_forwards_kind_to_search_stub() -> None:
    searcher = Searcher(
        [Space(id="alice/mcp", tags=["mcp-server"], runtime=Runtime(stage="RUNNING"))]
    )

    response = cli._search_response(
        "image editing",
        limit=1,
        sdk=None,
        filters=None,
        include_non_running=False,
        token=None,
        base_url="http://127.0.0.1:8080",
        kind="mcp",
        searcher=cast("SpaceSearcher", searcher),
    )

    assert [result.mediaType for result in response.results] == [MCP_SERVER_MEDIA_TYPE]


def test_cli_search_response_defaults_to_all_result_kinds() -> None:
    searcher = Searcher(
        [Space(id="alice/mcp", tags=["mcp-server"], runtime=Runtime(stage="RUNNING"))]
    )

    response = cli._search_response(
        "image editing",
        limit=2,
        sdk=None,
        filters=None,
        include_non_running=False,
        token=None,
        base_url="http://127.0.0.1:8080",
        searcher=cast("SpaceSearcher", searcher),
    )

    assert [result.mediaType for result in response.results] == [
        AI_SKILL_MEDIA_TYPE,
        MCP_SERVER_MEDIA_TYPE,
    ]


def test_cli_result_type_and_endpoint_support_inline_results() -> None:
    space = Space(id="alice/mcp", tags=["mcp-server"], runtime=Runtime(stage="RUNNING"))
    mcp_result = space_to_search_result(cast("SpaceSearchResultLike", space), kind="mcp")
    space_result = space_to_search_result(cast("SpaceSearchResultLike", space), kind="space")

    assert cli._result_type(mcp_result) == "mcp"
    assert cli._result_endpoint(mcp_result) == "https://alice-mcp.hf.space/gradio_api/mcp/sse"
    assert cli._result_type(space_result) == "space"
    assert cli._result_endpoint(space_result) == "https://alice-mcp.hf.space"


def test_hf_semantic_space_searcher_sends_agents_filter_and_token() -> None:
    SearchRequestRecorder.path = None
    SearchRequestRecorder.authorization = None
    httpd = HTTPServer(("127.0.0.1", 0), SearchHandler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    configured = "configured-token"

    try:
        searcher = HfSemanticSpaceSearcher(endpoint=f"http://127.0.0.1:{httpd.server_port}")
        results = list(
            searcher.search_spaces(
                "image editing",
                filter=["mcp-server"],
                include_non_running=True,
                token=configured,
            )
        )
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()

    assert [space.id for space in results] == ["alice/mcp"]
    assert SearchRequestRecorder.path is not None
    query = parse_qs(urlparse(SearchRequestRecorder.path).query)
    assert query == {
        "q": ["image editing"],
        "filter": ["mcp-server"],
        "includeNonRunning": ["true"],
        "agents": ["true"],
    }
    assert SearchRequestRecorder.authorization == f"Bearer {configured}"


def test_agent_finder_search_rejects_unsupported_media_type() -> None:
    response = search_agent_finder(
        SearchRequest(
            query=SearchQuery(text="image editing", mediaType="application/a2a-agent-card+json"),
            pageSize=5,
        )
    )

    assert response.results == []


def test_agent_finder_search_routes_mcp_media_type_to_mcp_results() -> None:
    searcher = Searcher(
        [Space(id="alice/mcp", tags=["mcp-server"], runtime=Runtime(stage="RUNNING"))]
    )

    response = search_agent_finder(
        SearchRequest(
            query=SearchQuery(text="image editing", mediaType=MCP_SERVER_MEDIA_TYPE),
            pageSize=5,
        ),
        search_spaces=lambda query, **kwargs: search_hf_spaces(
            query,
            searcher=cast("SpaceSearcher", searcher),
            **kwargs,
        ),
    )

    assert [result.mediaType for result in response.results] == [MCP_SERVER_MEDIA_TYPE]


def test_generated_skill_markdown_has_required_frontmatter() -> None:
    markdown = build_space_skill_markdown(
        space_id="mcp-tools/FLUX.1-Kontext-Dev",
        agents_md="# Use this Space\n\nCall the Space as documented.",
        title="FLUX.1 Kontext Dev",
        description="Use FLUX.1 Kontext Dev for image generation and editing.",
    )

    assert 'name: "hf-space-mcp-tools-flux-1-kontext-dev"' in markdown
    assert 'description: "Use FLUX.1 Kontext Dev for image generation and editing."' in markdown
    assert 'spaceId: "mcp-tools/FLUX.1-Kontext-Dev"' in markdown
    assert "# Use this Space" in markdown


def test_search_response_omits_null_and_default_fields() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/search",
        json={
            "query": {"text": "x", "mediaType": "application/a2a-agent-card+json"},
            "pageSize": 5,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"results": []}


def test_hf_token_from_headers_uses_precedence_order() -> None:
    selected = hf_token_from_headers(
        {
            "X-HF-Authorization": "Bearer x-hf-value",
            "Authorization": "Bearer auth-value",
            "HF_TOKEN": "hf-value",
        }
    )

    assert selected == "x-hf-value"


def test_hf_token_from_headers_uses_authorization_before_hf_token() -> None:
    selected = hf_token_from_headers({"Authorization": "Bearer auth-value", "HF_TOKEN": "hf-value"})

    assert selected == "auth-value"


def test_hf_token_from_headers_accepts_hf_token_header_without_bearer() -> None:
    assert hf_token_from_headers({"HF_TOKEN": " hf-value "}) == "hf-value"


def test_hf_token_from_headers_ignores_malformed_or_empty_headers() -> None:
    selected = hf_token_from_headers(
        {
            "X-HF-Authorization": "Token x-hf-value",
            "Authorization": "Bearer   ",
            "HF_TOKEN": "hf-value",
        }
    )

    assert selected == "hf-value"


def test_effective_hf_token_prefers_request_token() -> None:
    configured = "configured-token"
    request_value = "request-token"

    assert (
        effective_hf_token(request_token=request_value, configured_token=configured)
        == request_value
    )
    assert effective_hf_token(request_token=None, configured_token=configured) == configured


def test_search_route_forwards_effective_hf_token_to_search_stub() -> None:
    configured = "configured-token"
    search = RecordingSearch()
    client = TestClient(create_app(token=configured, search_spaces=search))

    first_response = client.post("/search", json=SEARCH_BODY, headers={"HF_TOKEN": "hf-token"})
    second_response = client.post("/search", json=SEARCH_BODY)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert search.tokens == ["hf-token", configured]


def test_openapi_documents_search_auth_headers() -> None:
    client = TestClient(create_app(search_spaces=RecordingSearch()))
    response = client.get("/openapi.json")

    assert response.status_code == 200
    search_operation = response.json()["paths"]["/search"]["post"]
    parameter_names = {parameter["name"] for parameter in search_operation["parameters"]}

    assert {"X-HF-Authorization", "Authorization", "HF_TOKEN"} <= parameter_names


def test_openapi_search_request_examples_hint_at_media_types() -> None:
    client = TestClient(create_app(search_spaces=RecordingSearch()))
    response = client.get("/openapi.json")

    assert response.status_code == 200
    search_operation = response.json()["paths"]["/search"]["post"]
    examples = search_operation["requestBody"]["content"]["application/json"]["examples"]

    assert examples["skill"]["value"]["query"]["mediaType"] == "application/ai-skill"
    assert (
        examples["huggingface-space"]["value"]["query"]["mediaType"]
        == "application/vnd.huggingface.space+json"
    )
    assert examples["mcp"]["value"]["query"]["mediaType"] == "application/mcp-server+json"


def test_agents_md_route_fetches_in_threadpool(monkeypatch) -> None:
    calls: list[tuple[object, tuple[object, ...]]] = []

    async def fake_run_in_threadpool(func, *args):
        calls.append((func, args))
        return func(*args)

    def fake_fetch_agents_md(space_id: str) -> str:
        return f"# Agents\n\n{space_id}"

    monkeypatch.setattr(server, "run_in_threadpool", fake_run_in_threadpool)
    monkeypatch.setattr(server, "fetch_agents_md", fake_fetch_agents_md)

    client = TestClient(create_app())
    response = client.get("/spaces/huggingface/alice/cool-space/agents.md")

    assert response.status_code == 200
    assert response.text == "# Agents\n\nalice/cool-space"
    assert calls == [(fake_fetch_agents_md, ("alice/cool-space",))]
