from __future__ import annotations

import itertools
import json
import re
from typing import TYPE_CHECKING, Literal, Protocol
from urllib.parse import quote

from agentfinder.hf_search import HfSemanticSpaceSearcher
from agentfinder.models import SearchResult

if TYPE_CHECKING:
    from collections.abc import Iterable

AI_SKILL_MEDIA_TYPE = "application/ai-skill"
MCP_SERVER_MEDIA_TYPE = "application/mcp-server+json"
HF_SPACE_MEDIA_TYPE = "application/vnd.huggingface.space+json"
LEGACY_HF_SPACE_MEDIA_TYPE = "application/huggingface-space+json"
HF_SOURCE = "https://huggingface.co"
DEFAULT_BASE_URL = "http://127.0.0.1:8080"
MCP_SERVER_TAG = "mcp-server"

SpaceResultKind = Literal["all", "skill", "space", "mcp"]


class SpaceRuntimeLike(Protocol):
    @property
    def stage(self) -> str | None: ...


class SpaceSearchResultLike(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def author(self) -> str: ...

    @property
    def title(self) -> str: ...

    @property
    def emoji(self) -> str | None: ...

    @property
    def sdk(self) -> str | None: ...

    @property
    def likes(self) -> int: ...

    @property
    def private(self) -> bool: ...

    @property
    def tags(self) -> list[str] | None: ...

    @property
    def runtime(self) -> SpaceRuntimeLike | None: ...

    @property
    def ai_short_description(self) -> str | None: ...

    @property
    def ai_category(self) -> str | None: ...

    @property
    def semantic_relevancy_score(self) -> float | None: ...

    @property
    def trending_score(self) -> int | None: ...


class SpaceSearcher(Protocol):
    def search_spaces(
        self,
        query: str,
        *,
        filter: str | Iterable[str] | None = None,
        sdk: str | list[str] | None = None,
        include_non_running: bool = False,
        token: bool | str | None = None,
        agents: bool = True,
    ) -> Iterable[SpaceSearchResultLike]: ...


def hf_space_url(space_id: str) -> str:
    return f"https://huggingface.co/spaces/{space_id}"


def hf_space_agents_md_url(space_id: str) -> str:
    split_space_id(space_id)
    return f"{hf_space_url(space_id)}/agents.md"


def hf_space_app_url(space_id: str) -> str:
    slug = space_id.replace("/", "-").replace("_", "-").replace(".", "-").lower()
    return f"https://{slug}.hf.space"


def hf_space_mcp_url(space_id: str, *, app_url: str | None = None) -> str:
    return f"{(app_url or hf_space_app_url(space_id)).rstrip('/')}/gradio_api/mcp/"


def hf_space_identifier(space_id: str) -> str:
    return f"urn:huggingface:space:{space_id.replace('/', ':')}"


def hf_space_skill_identifier(space_id: str) -> str:
    return f"urn:huggingface:skill:space:{space_id.replace('/', ':')}"


def hf_space_mcp_identifier(space_id: str) -> str:
    return f"urn:huggingface:mcp:space:{space_id.replace('/', ':')}"


def split_space_id(space_id: str) -> tuple[str, str]:
    owner, separator, name = space_id.partition("/")
    if not separator or not owner or not name:
        raise ValueError(f"Invalid Hugging Face Space id: {space_id!r}")
    return owner, name


def skill_name_for_space(space_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", space_id.lower()).strip("-")
    return f"hf-space-{slug}" or "hf-space"


def skill_url_for_space(space_id: str, *, base_url: str = DEFAULT_BASE_URL) -> str:
    owner, name = split_space_id(space_id)
    base = base_url.rstrip("/")
    return f"{base}/skills/huggingface/{quote(owner, safe='')}/{quote(name, safe='')}/SKILL.md"


def _space_tags(space: SpaceSearchResultLike) -> list[str]:
    tags = ["huggingface", "space"]
    if space.sdk:
        tags.append(space.sdk)
    if space.ai_category:
        tags.append(space.ai_category)
    tags.extend(space.tags or [])
    return list(dict.fromkeys(tags))


def _score(space: SpaceSearchResultLike) -> float:
    if space.semantic_relevancy_score is None:
        return 0.0
    return space.semantic_relevancy_score * 100


def _runtime_stage(space: SpaceSearchResultLike) -> str | None:
    return space.runtime.stage if space.runtime is not None else None


def _is_running_space(space: SpaceSearchResultLike) -> bool:
    return _runtime_stage(space) == "RUNNING"


def is_mcp_space(space: SpaceSearchResultLike) -> bool:
    return MCP_SERVER_TAG in (space.tags or [])


def _runtime_domain(space: SpaceSearchResultLike) -> str | None:
    domains: object = None
    if space.runtime is None:
        return None
    raw = getattr(space.runtime, "raw", None)
    if isinstance(raw, dict):
        domains = raw.get("domains")
    if not isinstance(domains, list):
        return None
    domain_values = (domain.get("domain") for domain in domains if isinstance(domain, dict))
    return next((value for value in domain_values if isinstance(value, str) and value), None)


def _space_app_url(space: SpaceSearchResultLike) -> str:
    domain = _runtime_domain(space)
    if domain is not None:
        return f"https://{domain}"
    return hf_space_app_url(space.id)


def _space_metadata(space: SpaceSearchResultLike) -> dict[str, object]:
    return {
        "spaceId": space.id,
        "author": space.author,
        "emoji": space.emoji,
        "sdk": space.sdk,
        "hubUrl": hf_space_url(space.id),
        "agentsMdUrl": hf_space_agents_md_url(space.id),
        "appUrl": _space_app_url(space),
        "category": space.ai_category,
        "likes": space.likes,
        "private": space.private,
        "runtimeStage": _runtime_stage(space),
        "trendingScore": space.trending_score,
    }


def space_to_space_result(space: SpaceSearchResultLike) -> SearchResult:
    return SearchResult(
        identifier=hf_space_identifier(space.id),
        displayName=space.title or space.id,
        mediaType=HF_SPACE_MEDIA_TYPE,
        data=_space_metadata(space),
        description=space.ai_short_description,
        tags=_space_tags(space),
        metadata={"sourceType": "huggingface-space"},
        score=_score(space),
        source=HF_SOURCE,
    )


def space_to_skill_result(
    space: SpaceSearchResultLike,
    *,
    base_url: str = DEFAULT_BASE_URL,
) -> SearchResult:
    return SearchResult(
        identifier=hf_space_skill_identifier(space.id),
        displayName=space.title or space.id,
        mediaType=AI_SKILL_MEDIA_TYPE,
        url=skill_url_for_space(space.id, base_url=base_url),
        description=space.ai_short_description,
        tags=_space_tags(space),
        metadata={
            "sourceType": "huggingface-space",
            **_space_metadata(space),
        },
        score=_score(space),
        source=HF_SOURCE,
    )


def space_to_mcp_result(space: SpaceSearchResultLike) -> SearchResult:
    return SearchResult(
        identifier=hf_space_mcp_identifier(space.id),
        displayName=f"{space.title or space.id} MCP Server",
        mediaType=MCP_SERVER_MEDIA_TYPE,
        data={
            "name": skill_name_for_space(space.id),
            "transport": "http",
            "url": hf_space_mcp_url(space.id, app_url=_space_app_url(space)),
        },
        description=space.ai_short_description,
        tags=_space_tags(space),
        metadata={
            "sourceType": "huggingface-space",
            **_space_metadata(space),
        },
        score=_score(space),
        source=HF_SOURCE,
    )


def space_to_search_result(
    space: SpaceSearchResultLike,
    *,
    kind: SpaceResultKind = "skill",
    base_url: str = DEFAULT_BASE_URL,
) -> SearchResult:
    if kind == "space":
        return space_to_space_result(space)
    if kind == "mcp":
        return space_to_mcp_result(space)
    return space_to_skill_result(space, base_url=base_url)


def _filters_for_kind(filters: list[str] | None, kind: SpaceResultKind) -> list[str] | None:
    if kind != "mcp":
        return filters
    if filters is None:
        return [MCP_SERVER_TAG]
    if MCP_SERVER_TAG in filters:
        return filters
    return [*filters, MCP_SERVER_TAG]


def _results_for_space(
    space: SpaceSearchResultLike,
    *,
    kind: SpaceResultKind,
    base_url: str,
) -> list[SearchResult]:
    if kind == "all":
        results = [space_to_skill_result(space, base_url=base_url)]
        if is_mcp_space(space):
            results.append(space_to_mcp_result(space))
        return results
    if kind == "mcp" and not is_mcp_space(space):
        return []
    return [space_to_search_result(space, kind=kind, base_url=base_url)]


def search_hf_spaces(
    query: str,
    *,
    limit: int = 10,
    sdk: list[str] | None = None,
    filters: list[str] | None = None,
    include_non_running: bool = False,
    token: bool | str | None = None,
    searcher: SpaceSearcher | None = None,
    kind: SpaceResultKind = "skill",
    base_url: str = DEFAULT_BASE_URL,
) -> list[SearchResult]:
    api = searcher or HfSemanticSpaceSearcher()
    results = api.search_spaces(
        query=query,
        filter=_filters_for_kind(filters, kind),
        sdk=sdk,
        include_non_running=include_non_running,
        token=token,
        agents=True,
    )
    running_results = (space for space in results if _is_running_space(space))
    search_results = itertools.chain.from_iterable(
        _results_for_space(space, kind=kind, base_url=base_url) for space in running_results
    )
    return list(itertools.islice(search_results, limit))


def _yaml_string(value: str) -> str:
    return json.dumps(value)


def build_space_skill_markdown(
    *,
    space_id: str,
    agents_md: str,
    title: str | None = None,
    description: str | None = None,
) -> str:
    skill_name = skill_name_for_space(space_id)
    skill_description = description or f"Use the Hugging Face Space {space_id}."
    heading = title or space_id

    return f"""---
name: {_yaml_string(skill_name)}
description: {_yaml_string(skill_description)}
metadata:
  source: huggingface-space
  spaceId: {_yaml_string(space_id)}
  hubUrl: {hf_space_url(space_id)}
  agentsMdUrl: {hf_space_agents_md_url(space_id)}
  appUrl: {hf_space_app_url(space_id)}
---

# Hugging Face Space: {heading}

Use this skill when the user wants to use the Hugging Face Space `{space_id}`.

- Space page: {hf_space_url(space_id)}
- App URL: {hf_space_app_url(space_id)}
- Source instructions: {hf_space_agents_md_url(space_id)}

## Space agent instructions

{agents_md.strip()}
"""
