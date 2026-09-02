from __future__ import annotations

import math
from typing import Any
from urllib.parse import urlparse

from openai import AsyncOpenAI, DefaultAsyncHttpxClient, OpenAIError

from location_extractor.ports import EntityResolutionRepository, MentionEmbedder, MentionReranker
from location_extractor.resolution import (
    EmbeddingCandidateDocument,
    EmbeddingVector,
    EntityMention,
    ResolutionCandidate,
    ResolutionFactor,
)


class EmbeddingProviderError(RuntimeError):
    pass


class OpenAICompatibleEmbedder:
    provider = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        base_url: str | None = None,
        dimensions: int | None = None,
        allow_insecure_http: bool = False,
        trust_env: bool = True,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if base_url and urlparse(base_url).scheme == "http" and not allow_insecure_http:
            raise ValueError(
                "plain HTTP embedding endpoint requires LOCATION_ALLOW_INSECURE_HTTP=true"
            )
        self.model = model
        self.dimensions = dimensions
        self.client = client or AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
            http_client=DefaultAsyncHttpxClient(trust_env=trust_env),
        )

    async def embed(self, texts: list[str]) -> list[EmbeddingVector]:
        if not texts:
            return []
        try:
            request: dict[str, Any] = {
                "model": self.model,
                "input": texts,
                "encoding_format": "float",
            }
            if self.dimensions is not None:
                request["dimensions"] = self.dimensions
            response = await self.client.embeddings.create(**request)
        except OpenAIError as exc:
            raise EmbeddingProviderError("embedding provider failed") from exc
        ordered = sorted(response.data, key=lambda item: item.index)
        if len(ordered) != len(texts):
            raise EmbeddingProviderError("embedding provider returned an unexpected vector count")
        vectors = [EmbeddingVector(values=list(item.embedding)) for item in ordered]
        dimensions = {len(vector.values) for vector in vectors}
        if len(dimensions) != 1 or any(
            not math.isfinite(value) for vector in vectors for value in vector.values
        ):
            raise EmbeddingProviderError("embedding provider returned invalid vectors")
        if any(_magnitude(vector.values) == 0 for vector in vectors):
            raise EmbeddingProviderError("embedding provider returned a zero vector")
        return vectors


class HybridEmbeddingCandidateRetriever:
    def __init__(
        self,
        repository: EntityResolutionRepository,
        embedder: MentionEmbedder,
        *,
        top_k: int = 3,
        corpus_limit: int = 1000,
    ) -> None:
        if top_k < 1 or corpus_limit < 1:
            raise ValueError("top_k and corpus_limit must be positive")
        self.repository = repository
        self.embedder = embedder
        self.top_k = top_k
        self.corpus_limit = corpus_limit

    async def retrieve(self, mention: EntityMention) -> list[ResolutionCandidate]:
        exact = self.repository.find_candidates(mention, limit=self.top_k)
        if exact:
            return exact
        documents = self.repository.list_embedding_documents(mention, limit=self.corpus_limit)
        if not documents:
            return []
        texts = [_mention_text(mention), *(_document_text(document) for document in documents)]
        vectors = await self.embedder.embed(texts)
        if len(vectors) != len(texts):
            raise EmbeddingProviderError("embedder returned an unexpected vector count")
        query = vectors[0].values
        ranked = sorted(
            zip(documents, vectors[1:], strict=True),
            key=lambda item: (
                -_cosine_similarity(query, item[1].values),
                str(item[0].entity.id),
            ),
        )
        return [
            ResolutionCandidate(
                entity=document.entity,
                matched_alias=document.texts[0],
                factors=[ResolutionFactor.EMBEDDING_SIMILARITY, *document.factors],
                specificity=document.specificity,
                similarity=_cosine_similarity(query, vector.values),
                supporting_texts=document.texts,
            )
            for document, vector in ranked[: self.top_k]
        ]


class RerankingCandidateRetriever:
    """Rerank embedding candidates without expanding their security scope."""

    def __init__(
        self,
        embedding_retriever: HybridEmbeddingCandidateRetriever,
        reranker: MentionReranker,
        *,
        top_n: int = 3,
    ) -> None:
        if top_n < 1:
            raise ValueError("top_n must be positive")
        self.embedding_retriever = embedding_retriever
        self.reranker = reranker
        self.top_n = top_n

    async def retrieve(self, mention: EntityMention) -> list[ResolutionCandidate]:
        candidates = await self.embedding_retriever.retrieve(mention)
        if not candidates or ResolutionFactor.EXACT_ALIAS in candidates[0].factors:
            return candidates
        documents = [_candidate_text(candidate) for candidate in candidates]
        results = await self.reranker.rerank(
            _mention_text(mention), documents, top_n=min(self.top_n, len(documents))
        )
        if len({result.index for result in results}) != len(results) or any(
            result.index >= len(candidates) for result in results
        ):
            raise EmbeddingProviderError("reranker returned invalid document indices")
        return [
            candidates[result.index].model_copy(
                update={
                    "factors": [
                        ResolutionFactor.RERANKER_SCORE,
                        *candidates[result.index].factors,
                    ],
                    "reranker_score": result.score,
                }
            )
            for result in results
        ]


def _mention_text(mention: EntityMention) -> str:
    components = [f"Entity type: {mention.entity_type.value}", f"Mention: {mention.text}"]
    if mention.context:
        components.append(f"Context: {mention.context}")
    return "\n".join(components)


def _document_text(document: EmbeddingCandidateDocument) -> str:
    return "\n".join(
        (
            f"Entity type: {document.entity.entity_type.value}",
            f"Canonical name: {document.entity.display_name}",
            f"Known mentions: {'; '.join(document.texts[1:])}",
        )
    )


def _candidate_text(candidate: ResolutionCandidate) -> str:
    return "\n".join(
        (
            f"Entity type: {candidate.entity.entity_type.value}",
            f"Canonical name: {candidate.entity.display_name}",
            f"Matched mention: {candidate.matched_alias}",
            f"Known mentions: {'; '.join(candidate.supporting_texts)}",
        )
    )


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise EmbeddingProviderError("embedding dimensions do not match")
    denominator = _magnitude(left) * _magnitude(right)
    if denominator == 0:
        raise EmbeddingProviderError("cannot compare a zero embedding vector")
    return sum(a * b for a, b in zip(left, right, strict=True)) / denominator


def _magnitude(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))
