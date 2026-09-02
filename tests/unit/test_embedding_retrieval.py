from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine

from location_extractor.db import Base, create_session_factory
from location_extractor.embedding_retrieval import (
    EmbeddingProviderError,
    HybridEmbeddingCandidateRetriever,
    OpenAICompatibleEmbedder,
    RerankingCandidateRetriever,
)
from location_extractor.resolution import (
    DeterministicResolutionPolicy,
    EmbeddingVector,
    EntityMention,
    EntityType,
    RerankResult,
    ResolutionOutcome,
    ResolutionScope,
)
from location_extractor.resolution_evaluation import (
    ResolutionPrediction,
    load_resolution_dataset,
    mention_for_case,
    score_resolution_predictions,
    seed_resolution_dataset,
)
from location_extractor.resolution_repository import SqlAlchemyEntityResolutionRepository

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "resolution_cases.json"


class SemanticFakeEmbedder:
    provider = "fake"
    model = "semantic-fixture"

    async def embed(self, texts: list[str]) -> list[EmbeddingVector]:
        return [EmbeddingVector(values=_semantic_vector(text)) for text in texts]


class FailingEmbedder:
    provider = "fake"
    model = "must-not-run"

    async def embed(self, texts: list[str]) -> list[EmbeddingVector]:
        raise AssertionError("exact aliases must not invoke embeddings")


class SemanticFakeReranker:
    provider = "fake"
    model = "semantic-reranker-fixture"

    async def rerank(self, query: str, documents: list[str], *, top_n: int) -> list[RerankResult]:
        query_vector = _semantic_vector(query)
        ranked = sorted(
            enumerate(documents),
            key=lambda item: sum(
                left * right
                for left, right in zip(query_vector, _semantic_vector(item[1]), strict=True)
            ),
            reverse=True,
        )
        return [
            RerankResult(index=index, score=1 - rank / 10)
            for rank, (index, _) in enumerate(ranked[:top_n])
        ]


class FailingReranker:
    provider = "fake"
    model = "must-not-run"

    async def rerank(self, query: str, documents: list[str], *, top_n: int) -> list[RerankResult]:
        raise AssertionError("exact aliases must not invoke reranking")


def _semantic_vector(text: str) -> list[float]:
    lowered = text.casefold()
    semantic_groups = (
        ("canonical name: john smith", "mention: john s.", "mention: john from operations"),
        ("canonical name: john carter",),
        ("canonical name: downtown office", "mention: central branch"),
        ("canonical name: north warehouse", "mention: warehouse up north"),
        (
            "canonical name: alex lee (operations)",
            "mention: alex lee from the warehouse team",
        ),
        ("canonical name: alex lee (design)", "mention: alex lee from product design"),
        ("canonical name: central logistics hub", "mention: central hub for freight shipments"),
        ("canonical name: central community hub", "mention: central hub for neighborhood events"),
        ("canonical name: north research campus", "mention: north site used by the laboratory"),
        ("canonical name: north sales office", "mention: north site for regional sales"),
    )
    for index, markers in enumerate(semantic_groups):
        if any(marker in lowered for marker in markers):
            vector = [0.0] * len(semantic_groups)
            vector[index] = 1.0
            return vector
    return [0.1] * len(semantic_groups)


@pytest.fixture
def repository(tmp_path: Path) -> SqlAlchemyEntityResolutionRepository:
    database_url = f"sqlite:///{tmp_path}/embedding.db"
    Base.metadata.create_all(create_engine(database_url))
    repository = SqlAlchemyEntityResolutionRepository(create_session_factory(database_url))
    seed_resolution_dataset(repository, load_resolution_dataset(FIXTURE_PATH))
    return repository


async def test_hybrid_retrieval_improves_recall_without_automatic_semantic_links(
    repository: SqlAlchemyEntityResolutionRepository,
) -> None:
    dataset = load_resolution_dataset(FIXTURE_PATH)
    retriever = HybridEmbeddingCandidateRetriever(repository, SemanticFakeEmbedder(), top_k=3)
    policy = DeterministicResolutionPolicy()
    predictions: list[ResolutionPrediction] = []
    for case in dataset.cases:
        mention = mention_for_case(case)
        candidates = await retriever.retrieve(mention)
        predictions.append(
            ResolutionPrediction(
                candidates=candidates,
                decision=policy.decide(mention, candidates),
            )
        )

    report = score_resolution_predictions(dataset, predictions)
    assert report.metrics.candidate_recall_at_3 == 1
    assert report.metrics.top_1_accuracy == 1
    assert report.metrics.resolved_precision == 1
    assert report.tenant_leakage_count == 0
    assert report.entity_type_leakage_count == 0
    semantic_results = report.cases[-4:]
    assert all(
        result.predicted_outcome is ResolutionOutcome.UNRESOLVED for result in semantic_results
    )


async def test_exact_alias_short_circuits_embedding_provider(
    repository: SqlAlchemyEntityResolutionRepository,
) -> None:
    retriever = HybridEmbeddingCandidateRetriever(repository, FailingEmbedder(), top_k=3)
    candidates = await retriever.retrieve(
        EntityMention(
            entity_type=EntityType.PERSON,
            text="John",
            scope=ResolutionScope(tenant_id="tenant-alpha", conversation_id="conv-carter"),
        )
    )
    assert candidates[0].entity.display_name == "John Carter"


async def test_reranker_only_reorders_scoped_embedding_candidates(
    repository: SqlAlchemyEntityResolutionRepository,
) -> None:
    embedding = HybridEmbeddingCandidateRetriever(repository, SemanticFakeEmbedder(), top_k=3)
    retriever = RerankingCandidateRetriever(embedding, SemanticFakeReranker(), top_n=2)
    candidates = await retriever.retrieve(
        EntityMention(
            entity_type=EntityType.PERSON,
            text="John from operations",
            context="John from operations will join the warehouse inspection.",
            scope=ResolutionScope(tenant_id="tenant-alpha", conversation_id="conv-ops"),
        )
    )
    assert candidates[0].entity.display_name == "John Smith"
    assert candidates[0].reranker_score == 1
    assert all(candidate.entity.tenant_id == "tenant-alpha" for candidate in candidates)


async def test_exact_alias_short_circuits_reranker(
    repository: SqlAlchemyEntityResolutionRepository,
) -> None:
    embedding = HybridEmbeddingCandidateRetriever(repository, FailingEmbedder(), top_k=3)
    retriever = RerankingCandidateRetriever(embedding, FailingReranker(), top_n=2)
    candidates = await retriever.retrieve(
        EntityMention(
            entity_type=EntityType.PERSON,
            text="John",
            scope=ResolutionScope(tenant_id="tenant-alpha", conversation_id="conv-carter"),
        )
    )
    assert candidates[0].entity.display_name == "John Carter"


def test_embedding_documents_exclude_aliases_from_other_scopes(
    repository: SqlAlchemyEntityResolutionRepository,
) -> None:
    documents = repository.list_embedding_documents(
        EntityMention(
            entity_type=EntityType.LOCATION,
            text="office",
            scope=ResolutionScope(tenant_id="tenant-alpha", conversation_id="conv-other"),
        )
    )
    downtown = next(
        document for document in documents if document.entity.display_name == "Downtown Office"
    )
    assert "downtown office" in downtown.texts
    assert "the office" not in downtown.texts


class FakeEmbeddingsEndpoint:
    def __init__(self, vectors: list[list[float]]) -> None:
        self.vectors = vectors
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        data = [
            SimpleNamespace(index=index, embedding=vector)
            for index, vector in reversed(list(enumerate(self.vectors)))
        ]
        return SimpleNamespace(data=data)


async def test_openai_embedding_adapter_preserves_input_order() -> None:
    endpoint = FakeEmbeddingsEndpoint([[1.0, 0.0], [0.0, 1.0]])
    embedder = OpenAICompatibleEmbedder(
        api_key="not-used",
        model="embedding-test",
        timeout_seconds=1,
        max_retries=0,
        client=SimpleNamespace(embeddings=endpoint),
    )
    vectors = await embedder.embed(["first", "second"])
    assert [vector.values for vector in vectors] == [[1.0, 0.0], [0.0, 1.0]]
    assert endpoint.kwargs["input"] == ["first", "second"]
    assert "dimensions" not in endpoint.kwargs


async def test_openai_embedding_adapter_rejects_invalid_vector_count() -> None:
    embedder = OpenAICompatibleEmbedder(
        api_key="not-used",
        model="embedding-test",
        timeout_seconds=1,
        max_retries=0,
        client=SimpleNamespace(embeddings=FakeEmbeddingsEndpoint([[1.0, 0.0]])),
    )
    with pytest.raises(EmbeddingProviderError, match="vector count"):
        await embedder.embed(["first", "second"])


def test_plain_http_embedding_endpoint_requires_explicit_opt_in() -> None:
    with pytest.raises(ValueError, match="ALLOW_INSECURE_HTTP"):
        OpenAICompatibleEmbedder(
            api_key="secret",
            model="embedding-test",
            timeout_seconds=1,
            max_retries=0,
            base_url="http://embeddings.internal/v1",
        )
