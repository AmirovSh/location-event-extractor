from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from location_extractor.domain import (
    CandidateOutcome,
    ExtractionResult,
    ParsedMessage,
    ProcessResult,
    RunStatus,
)
from location_extractor.resolution import (
    CandidateSetVerification,
    CanonicalEntity,
    EmbeddingCandidateDocument,
    EmbeddingVector,
    EntityAlias,
    EntityMention,
    PairwiseVerification,
    RerankResult,
    ResolutionCandidate,
    ResolutionDecision,
)


class LocationCandidateDetector(Protocol):
    async def is_relevant(self, message: ParsedMessage) -> bool: ...


class MessageProcessor(Protocol):
    async def process(self, message: ParsedMessage) -> ProcessResult: ...


class LocationEventExtractor(Protocol):
    @property
    def provider(self) -> str | None: ...

    @property
    def model(self) -> str | None: ...

    async def extract(self, message: ParsedMessage) -> ExtractionResult: ...


class LocationEventRepository(Protocol):
    def get_result(
        self, message: ParsedMessage, extractor_version: str, schema_version: str
    ) -> ProcessResult | None: ...

    def save_result(
        self,
        message: ParsedMessage,
        extractor_version: str,
        schema_version: str,
        provider: str | None,
        model: str | None,
        status: RunStatus,
        outcomes: list[CandidateOutcome],
        latency_ms: int,
    ) -> ProcessResult: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new(self) -> UUID: ...


class EntityResolutionRepository(Protocol):
    def save_entity(
        self, entity: CanonicalEntity, aliases: list[EntityAlias]
    ) -> CanonicalEntity: ...

    def save_mention(self, mention: EntityMention) -> EntityMention: ...

    def find_candidates(
        self, mention: EntityMention, *, limit: int = 10
    ) -> list[ResolutionCandidate]: ...

    def list_embedding_documents(
        self, mention: EntityMention, *, limit: int = 1000
    ) -> list[EmbeddingCandidateDocument]: ...

    def save_decision(self, decision: ResolutionDecision) -> ResolutionDecision: ...

    def get_active_decision(self, mention_id: UUID) -> ResolutionDecision | None: ...


class EntityResolutionPolicy(Protocol):
    def decide(
        self, mention: EntityMention, candidates: list[ResolutionCandidate]
    ) -> ResolutionDecision: ...


class ResolutionDecisionRepository(Protocol):
    def save_mention(self, mention: EntityMention) -> EntityMention: ...

    def get_active_decision(self, mention_id: UUID) -> ResolutionDecision | None: ...

    def save_decision(self, decision: ResolutionDecision) -> ResolutionDecision: ...

    def promote_alias(self, alias: EntityAlias) -> bool: ...


class EntityCandidateRetriever(Protocol):
    async def retrieve(self, mention: EntityMention) -> list[ResolutionCandidate]: ...


class MentionEmbedder(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def embed(self, texts: list[str]) -> list[EmbeddingVector]: ...


class MentionReranker(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def rerank(
        self, query: str, documents: list[str], *, top_n: int
    ) -> list[RerankResult]: ...


class PairwiseEntityVerifier(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def verify(
        self, mention: EntityMention, candidate: ResolutionCandidate
    ) -> PairwiseVerification: ...


class CandidateSetEntityVerifier(Protocol):
    async def verify_candidate_set(
        self, mention: EntityMention, candidates: list[ResolutionCandidate]
    ) -> CandidateSetVerification: ...
