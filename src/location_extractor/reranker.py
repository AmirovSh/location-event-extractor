from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlparse

import httpx

from location_extractor.resolution import RerankResult


class RerankerProviderError(RuntimeError):
    pass


class OpenAICompatibleReranker:
    """Adapter for the common POST /rerank model API."""

    provider = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_retries: int = 2,
        allow_insecure_http: bool = False,
        trust_env: bool = True,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if urlparse(base_url).scheme == "http" and not allow_insecure_http:
            raise ValueError(
                "plain HTTP reranker endpoint requires LOCATION_ALLOW_INSECURE_HTTP=true"
            )
        self.model = model
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self._max_retries = max_retries
        self._authorization = f"Bearer {api_key}"
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_seconds,
            trust_env=trust_env,
        )

    async def rerank(self, query: str, documents: list[str], *, top_n: int) -> list[RerankResult]:
        if not documents:
            return []
        if not 1 <= top_n <= len(documents):
            raise ValueError("top_n must be within the document count")
        try:
            response = await self._post_with_retries(query, documents, top_n)
            response.raise_for_status()
            payload: Any = response.json()
            raw_results = payload["results"]
            results = [
                RerankResult(index=item["index"], score=item["relevance_score"])
                for item in raw_results
            ]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise RerankerProviderError("reranker provider returned an invalid response") from exc
        if len(results) > top_n:
            raise RerankerProviderError("reranker returned too many results")
        return results

    async def _post_with_retries(
        self, query: str, documents: list[str], top_n: int
    ) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.post(
                    "rerank",
                    headers={"Authorization": self._authorization},
                    json={
                        "model": self.model,
                        "query": query,
                        "documents": documents,
                        "top_n": top_n,
                    },
                )
            except httpx.RequestError:
                if attempt == self._max_retries:
                    raise
            else:
                if response.status_code != 429 and response.status_code < 500:
                    return response
                if attempt == self._max_retries:
                    return response
            await asyncio.sleep(0.25 * 2**attempt)
        raise AssertionError("retry loop must return or raise")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
