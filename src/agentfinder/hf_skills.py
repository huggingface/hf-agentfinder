from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from agentfinder.hf_spaces import AI_SKILL_MEDIA_TYPE
from agentfinder.models import SearchResult

HF_SKILLS_SOURCE = "https://github.com/huggingface/skills"
HF_SKILLS_PUBLISHER = "huggingface/skills"
DEFAULT_MEILI_INDEX = "hf_skills"
SKILL_MARKDOWN_FILENAME = "SKILL.md"


def _configured_meili_url(meili_url: str | None) -> str | None:
    value = meili_url or os.environ.get("AGENTFINDER_MEILI_URL")
    if value is None:
        return None
    stripped = value.strip().rstrip("/")
    return stripped or None


def _meili_api_key(api_key: str | None) -> str | None:
    value = api_key if api_key is not None else os.environ.get("MEILI_MASTER_KEY")
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _string(hit: dict[str, Any], key: str) -> str | None:
    value = hit.get(key)
    return value if isinstance(value, str) and value else None


def _ranking_score(hit: dict[str, Any]) -> float:
    value = hit.get("_rankingScore")
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _skill_key(hit: dict[str, Any]) -> str:
    return _string(hit, "skill") or _string(hit, "path") or _string(hit, "id") or "unknown"


def _skill_identifier(skill: str) -> str:
    return f"urn:ai:github.com:huggingface:skills:{skill.replace('/', ':')}"


def _skill_directory_path(value: str) -> str:
    stripped = value.strip().rstrip("/")
    suffix = f"/{SKILL_MARKDOWN_FILENAME}"
    if stripped.endswith(suffix):
        return stripped[: -len(suffix)]
    if stripped == SKILL_MARKDOWN_FILENAME:
        return ""
    return stripped


def _github_tree_url_for_skill_artifact(url: str) -> str:
    directory_url = _skill_directory_path(url)
    return directory_url.replace("/blob/", "/tree/", 1)


def _skill_url(hit: dict[str, Any]) -> str:
    url = _string(hit, "url")
    if url is not None:
        return _github_tree_url_for_skill_artifact(url)

    path = _string(hit, "path")
    if path is not None:
        directory_path = _skill_directory_path(path)
        if directory_path:
            return f"{HF_SKILLS_SOURCE}/tree/main/{directory_path}"

    raw_url = _string(hit, "raw_url")
    if raw_url is not None:
        return _github_tree_url_for_skill_artifact(raw_url)

    return f"{HF_SKILLS_SOURCE}/tree/main"


def _metadata_value(hit: dict[str, Any], key: str) -> Any:
    value = hit[key]
    if key == "path" and isinstance(value, str):
        return _skill_directory_path(value)
    if key == "url" and isinstance(value, str):
        return _github_tree_url_for_skill_artifact(value)
    return value


def _search_result_from_hit(hit: dict[str, Any]) -> SearchResult:
    skill = _skill_key(hit)
    ranking_score = _ranking_score(hit)
    description = (
        _string(hit, "marketplace_description")
        or _string(hit, "skill_description")
        or _string(hit, "title")
    )
    metadata: dict[str, Any] = {
        "sourceType": "huggingface-skills",
        "publisher": HF_SKILLS_PUBLISHER,
        "rankingScore": ranking_score,
    }
    for key in [
        "id",
        "repo",
        "skill",
        "skill_name",
        "path",
        "raw_url",
        "kind",
        "title",
        "heading_path",
        "version",
        "updated_at",
        "ordinal",
        "part",
    ]:
        if key in hit:
            metadata[key] = _metadata_value(hit, key)

    return SearchResult(
        identifier=_skill_identifier(skill),
        displayName=_string(hit, "skill_name") or skill,
        type=AI_SKILL_MEDIA_TYPE,
        url=_skill_url(hit),
        description=description,
        tags=["huggingface", "skills"],
        metadata=metadata,
        score=ranking_score * 100,
        source=HF_SKILLS_SOURCE,
    )


def _best_skill_hits(hits: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    best_by_skill: dict[str, dict[str, Any]] = {}
    for hit in hits:
        skill = _skill_key(hit)
        current = best_by_skill.get(skill)
        if current is None or _ranking_score(hit) > _ranking_score(current):
            best_by_skill[skill] = hit
    return sorted(best_by_skill.values(), key=_ranking_score, reverse=True)[:limit]


def search_hf_skills(
    query: str,
    *,
    limit: int = 10,
    meili_url: str | None = None,
    index: str | None = None,
    api_key: str | None = None,
) -> list[SearchResult]:
    configured_url = _configured_meili_url(meili_url)
    if configured_url is None:
        return []

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "agentfinder/0.1",
    }
    key = _meili_api_key(api_key)
    if key is not None:
        headers["Authorization"] = f"Bearer {key}"

    body = {
        "q": query,
        "limit": limit * 3,
        "showRankingScore": True,
        "showRankingScoreDetails": False,
    }
    index_name = index or os.environ.get("AGENTFINDER_MEILI_INDEX", DEFAULT_MEILI_INDEX)
    request = UrlRequest(  # noqa: S310 - configured local/admin Meilisearch URL.
        f"{configured_url}/indexes/{index_name}/search",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310
            payload = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return []

    hits = payload.get("hits", [])
    if not isinstance(hits, list):
        return []
    dict_hits = [hit for hit in hits if isinstance(hit, dict)]
    return [_search_result_from_hit(hit) for hit in _best_skill_hits(dict_hits, limit)]
