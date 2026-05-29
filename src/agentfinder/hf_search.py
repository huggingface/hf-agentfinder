from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from collections.abc import Iterable

HF_ENDPOINT = "https://huggingface.co"
SEMANTIC_SEARCH_PATH = "/api/spaces/semantic-search"
USER_AGENT = "agentfinder/0.1"


@dataclass
class SpaceRuntime:
    stage: str | None
    raw: dict[str, object]


class SpaceSearchResult:
    def __init__(self, data: dict[str, object]) -> None:
        runtime = data.get("runtime")
        runtime_data = cast("dict[str, object]", runtime) if isinstance(runtime, dict) else None
        self.id = _string(data.get("id"))
        self.author = _string(data.get("author"))
        self.title = _string(data.get("title"))
        self.host = _optional_string(data.get("host"))
        self.subdomain = _optional_string(data.get("subdomain"))
        self.emoji = _optional_string(data.get("emoji"))
        self.sdk = _optional_string(data.get("sdk"))
        self.likes = _integer(data.get("likes"))
        self.private = data.get("private") is True
        self.tags = _string_list(data.get("tags"))
        self.runtime = (
            SpaceRuntime(stage=_optional_string(runtime_data.get("stage")), raw=runtime_data)
            if runtime_data is not None
            else None
        )
        self.ai_short_description = _optional_string(data.get("ai_short_description"))
        self.ai_category = _optional_string(data.get("ai_category"))
        self.semantic_relevancy_score = _optional_float(data.get("semanticRelevancyScore"))
        self.trending_score = _optional_integer(data.get("trendingScore"))


class HfSemanticSpaceSearcher:
    def __init__(self, *, endpoint: str = HF_ENDPOINT) -> None:
        self.endpoint = endpoint.rstrip("/")

    def search_spaces(
        self,
        query: str,
        *,
        filter: str | Iterable[str] | None = None,
        sdk: str | list[str] | None = None,
        include_non_running: bool = False,
        token: bool | str | None = None,
        agents: bool = True,
    ) -> Iterable[SpaceSearchResult]:
        params: dict[str, object] = {"q": query}
        if filter is not None:
            params["filter"] = filter
        if sdk is not None:
            params["sdk"] = sdk
        if include_non_running:
            params["includeNonRunning"] = "true"
        if agents:
            params["agents"] = "true"

        url = f"{self.endpoint}{SEMANTIC_SEARCH_PATH}?{urlencode(params, doseq=True)}"
        headers = {"User-Agent": USER_AGENT}
        if isinstance(token, str):
            headers["Authorization"] = f"Bearer {token}"

        request = Request(url, headers=headers)  # noqa: S310 - public HF API endpoint
        with urlopen(request, timeout=30) as response:  # noqa: S310 - public HF API endpoint
            data = json.loads(response.read().decode("utf-8"))

        if not isinstance(data, list):
            return []
        return [SpaceSearchResult(item) for item in data if isinstance(item, dict)]


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _integer(value: object) -> int:
    return value if isinstance(value, int) else 0


def _optional_integer(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _string_list(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    return [item for item in value if isinstance(item, str)]
