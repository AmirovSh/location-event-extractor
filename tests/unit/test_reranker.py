from __future__ import annotations

import json

import httpx
import pytest

from location_extractor.reranker import OpenAICompatibleReranker, RerankerProviderError


async def test_reranker_adapter_maps_ranked_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload == {
            "model": "reranker-test",
            "query": "query",
            "documents": ["first", "second"],
            "top_n": 2,
        }
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.2},
                ]
            },
        )

    client = httpx.AsyncClient(
        base_url="https://reranker.example/v1/",
        transport=httpx.MockTransport(handler),
    )
    adapter = OpenAICompatibleReranker(
        api_key="secret",
        base_url="https://reranker.example/v1",
        model="reranker-test",
        timeout_seconds=1,
        client=client,
    )
    results = await adapter.rerank("query", ["first", "second"], top_n=2)
    assert [(result.index, result.score) for result in results] == [(1, 0.9), (0, 0.2)]
    await client.aclose()


async def test_reranker_adapter_rejects_malformed_response() -> None:
    client = httpx.AsyncClient(
        base_url="https://reranker.example/v1/",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    adapter = OpenAICompatibleReranker(
        api_key="secret",
        base_url="https://reranker.example/v1",
        model="reranker-test",
        timeout_seconds=1,
        client=client,
    )
    with pytest.raises(RerankerProviderError, match="invalid response"):
        await adapter.rerank("query", ["document"], top_n=1)
    await client.aclose()


async def test_reranker_adapter_retries_transient_failure() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.8}]})

    client = httpx.AsyncClient(
        base_url="https://reranker.example/v1/",
        transport=httpx.MockTransport(handler),
    )
    adapter = OpenAICompatibleReranker(
        api_key="secret",
        base_url="https://reranker.example/v1",
        model="reranker-test",
        timeout_seconds=1,
        max_retries=1,
        client=client,
    )
    results = await adapter.rerank("query", ["document"], top_n=1)
    assert attempts == 2
    assert results[0].score == 0.8
    await client.aclose()


def test_plain_http_reranker_requires_explicit_opt_in() -> None:
    with pytest.raises(ValueError, match="ALLOW_INSECURE_HTTP"):
        OpenAICompatibleReranker(
            api_key="secret",
            base_url="http://reranker.internal/v1",
            model="reranker-test",
            timeout_seconds=1,
        )
