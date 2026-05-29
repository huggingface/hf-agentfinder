from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FederationMode = Literal["auto", "referrals", "none"]


class CatalogEntry(BaseModel):
    """Agent Finder catalog entry using v0.5 field names."""

    model_config = ConfigDict(extra="allow")

    identifier: str
    displayName: str
    type: str
    url: str | None = None
    data: dict[str, Any] | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    representativeQueries: list[str] = Field(default_factory=list)
    version: str | None = None
    updatedAt: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    trustManifest: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_value_or_reference(self) -> CatalogEntry:
        if (self.url is None) == (self.data is None):
            raise ValueError("exactly one of url or data must be present")
        return self


class SearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(
        description="Natural-language search query, for example 'remove image background'.",
        examples=["remove image background"],
    )
    filter: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Structured field-path constraints. Use `type` to constrain artifact media "
            "types, for example `{'type': ['application/mcp-server+json']}`."
        ),
        examples=[
            {"type": ["application/ai-skill"]},
            {"type": ["application/vnd.huggingface.space+json"]},
            {"type": ["application/mcp-server+json"]},
        ],
    )


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: SearchQuery
    federation: FederationMode = Field(
        default="auto",
        description="Federation mode requested by the client: auto, referrals, or none.",
    )
    pageSize: int = Field(default=10, ge=1, le=100, description="Maximum results to return.")
    pageToken: str | None = Field(
        default=None,
        description="Opaque pagination token from a previous response, when supported.",
    )


class SearchResult(CatalogEntry):
    score: float
    source: str


class SearchResponse(BaseModel):
    results: list[SearchResult]
    referrals: list[CatalogEntry] = Field(default_factory=list)
    pageToken: str | None = None
