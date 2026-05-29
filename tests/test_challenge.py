from __future__ import annotations

from fastapi.testclient import TestClient

from agentfinder.challenge import (
    A2A_AGENT_MEDIA_TYPE,
    AI_CATALOG_MEDIA_TYPE,
    AI_REGISTRY_MEDIA_TYPE,
    create_challenge_app,
)
from agentfinder.hf_spaces import AI_SKILL_MEDIA_TYPE, MCP_SERVER_MEDIA_TYPE


def test_challenge_root_search_returns_mixed_result_types_and_referrals() -> None:
    client = TestClient(create_challenge_app())

    response = client.post(
        "/search",
        json={
            "query": {"text": "find tools registries and skills"},
            "federation": "referrals",
            "pageSize": 20,
        },
    )

    assert response.status_code == 200
    body = response.json()
    media_types = {result["type"] for result in body["results"]}
    assert {
        AI_SKILL_MEDIA_TYPE,
        MCP_SERVER_MEDIA_TYPE,
        A2A_AGENT_MEDIA_TYPE,
        AI_CATALOG_MEDIA_TYPE,
        AI_REGISTRY_MEDIA_TYPE,
    } <= media_types
    assert {referral["type"] for referral in body["referrals"]} == {AI_REGISTRY_MEDIA_TYPE}


def test_challenge_search_filters_by_media_type() -> None:
    client = TestClient(create_challenge_app())

    response = client.post(
        "/search",
        json={
            "query": {"text": "tool server", "filter": {"type": [MCP_SERVER_MEDIA_TYPE]}},
            "pageSize": 10,
        },
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert results
    assert {result["type"] for result in results} == {MCP_SERVER_MEDIA_TYPE}


def test_challenge_nested_registry_refers_to_deep_registry() -> None:
    client = TestClient(create_challenge_app())

    response = client.post(
        "/registries/nested/search",
        json={
            "query": {"text": "walk deeper registries"},
            "federation": "referrals",
            "pageSize": 5,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["referrals"][0]["url"].endswith("/registries/deep/search")

    deep_response = client.post(
        "/registries/deep/search",
        json={"query": {"text": "leaf artifacts"}, "pageSize": 5},
    )
    assert deep_response.status_code == 200
    assert {result["type"] for result in deep_response.json()["results"]} == {
        AI_SKILL_MEDIA_TYPE,
        MCP_SERVER_MEDIA_TYPE,
    }


def test_challenge_artifact_routes_are_fetchable() -> None:
    client = TestClient(create_challenge_app())

    skill_response = client.get("/artifacts/skills/triage-skill/SKILL.md")
    mcp_response = client.get("/artifacts/mcp/echo-tools")
    catalog_response = client.get("/.well-known/ai-catalog.json")

    assert skill_response.status_code == 200
    assert 'name: "triage-skill"' in skill_response.text
    assert mcp_response.status_code == 200
    assert mcp_response.json()["tools"][0]["name"] == "challenge_echo"
    assert catalog_response.status_code == 200
    assert catalog_response.json()["host"]["displayName"] == "Agent Finder Challenge Registry"
