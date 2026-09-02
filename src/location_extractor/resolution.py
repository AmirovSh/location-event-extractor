from __future__ import annotations

import hashlib
import unicodedata
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EntityType(StrEnum):
    PERSON = "PERSON"
    LOCATION = "LOCATION"


class ResolutionOutcome(StrEnum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    NEW_ENTITY = "NEW_ENTITY"
    UNRESOLVED = "UNRESOLVED"


class ResolutionConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class AliasSource(StrEnum):
    SEED = "SEED"
    MANUAL = "MANUAL"
    AUTO_RESOLUTION = "AUTO_RESOLUTION"


class ResolutionFactor(StrEnum):
    EXACT_ALIAS = "EXACT_ALIAS"
    SAME_TENANT = "SAME_TENANT"
    SAME_SOURCE = "SAME_SOURCE"
    SAME_CONVERSATION = "SAME_CONVERSATION"
    SAME_SENDER = "SAME_SENDER"
    EMBEDDING_SIMILARITY = "EMBEDDING_SIMILARITY"
    RERANKER_SCORE = "RERANKER_SCORE"
    PAIRWISE_VERIFICATION = "PAIRWISE_VERIFICATION"


class ResolutionScope(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, frozen=True)

    tenant_id: str = Field(min_length=1, max_length=512)
    source_id: str | None = Field(default=None, max_length=512)
    conversation_id: str | None = Field(default=None, max_length=512)
    sender_id: str | None = Field(default=None, max_length=512)


class CanonicalEntity(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, frozen=True)

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str = Field(min_length=1, max_length=512)
    entity_type: EntityType
    display_name: str = Field(min_length=1, max_length=1024)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EntityAlias(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, frozen=True)

    id: UUID = Field(default_factory=uuid4)
    canonical_entity_id: UUID
    alias: str = Field(min_length=1, max_length=1024)
    scope: ResolutionScope
    source: AliasSource
    active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def normalized_alias(self) -> str:
        return normalize_mention(self.alias)


class EntityMention(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, frozen=True)

    id: UUID = Field(default_factory=uuid4)
    entity_type: EntityType
    text: str = Field(min_length=1, max_length=1024)
    scope: ResolutionScope
    source_message_id: UUID | None = None
    context: str | None = Field(default=None, max_length=4000, exclude=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def normalized_text(self) -> str:
        return normalize_mention(self.text)

    @property
    def context_hash(self) -> str | None:
        return hashlib.sha256(self.context.encode()).hexdigest() if self.context else None


class ResolutionCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    entity: CanonicalEntity
    matched_alias: str
    factors: list[ResolutionFactor]
    specificity: int = Field(ge=0, le=3)
    similarity: float | None = Field(default=None, ge=-1, le=1)
    reranker_score: float | None = None
    supporting_texts: list[str] = Field(default_factory=list)


class EmbeddingCandidateDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    entity: CanonicalEntity
    texts: list[str] = Field(min_length=1)
    factors: list[ResolutionFactor]
    specificity: int = Field(ge=0, le=3)


class EmbeddingVector(BaseModel):
    model_config = ConfigDict(frozen=True)

    values: list[float] = Field(min_length=1)


class RerankResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=0)
    score: float


class VerificationVerdict(StrEnum):
    SAME_ENTITY = "SAME_ENTITY"
    DIFFERENT_ENTITY = "DIFFERENT_ENTITY"
    UNCERTAIN = "UNCERTAIN"


class PairwiseVerification(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdict: VerificationVerdict
    confidence: ResolutionConfidence
    supporting_signals: list[str] = Field(default_factory=list, max_length=5)
    contradicting_signals: list[str] = Field(default_factory=list, max_length=5)
    insufficient_context: bool


class CandidateSetVerdict(StrEnum):
    UNIQUE_MATCH = "UNIQUE_MATCH"
    NO_MATCH = "NO_MATCH"
    AMBIGUOUS = "AMBIGUOUS"


class CandidateSetVerification(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdict: CandidateSetVerdict
    selected_candidate_position: int | None = Field(default=None, ge=1)
    confidence: ResolutionConfidence
    supporting_signals: list[str] = Field(default_factory=list, max_length=5)
    contradicting_signals: list[str] = Field(default_factory=list, max_length=5)
    insufficient_context: bool

    @model_validator(mode="after")
    def validate_selection(self) -> CandidateSetVerification:
        if self.verdict is CandidateSetVerdict.UNIQUE_MATCH:
            if self.selected_candidate_position is None:
                raise ValueError("UNIQUE_MATCH requires selected_candidate_position")
        elif self.selected_candidate_position is not None:
            raise ValueError("only UNIQUE_MATCH may select a candidate position")
        return self


class ResolutionDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    mention_id: UUID
    outcome: ResolutionOutcome
    confidence: ResolutionConfidence
    canonical_entity_id: UUID | None = None
    candidate_entity_ids: list[UUID] = Field(default_factory=list)
    factors: list[ResolutionFactor] = Field(default_factory=list)
    resolver_version: str = Field(min_length=1, max_length=128)
    active: bool = True
    supersedes_resolution_id: UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def require_consistent_target(self) -> ResolutionDecision:
        if self.outcome is ResolutionOutcome.RESOLVED and self.canonical_entity_id is None:
            raise ValueError("RESOLVED decision requires canonical_entity_id")
        if self.outcome is not ResolutionOutcome.RESOLVED and self.canonical_entity_id is not None:
            raise ValueError("only RESOLVED decision may have canonical_entity_id")
        return self


class MentionResolutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    mention_id: UUID
    entity_type: EntityType
    mention_text: str
    outcome: ResolutionOutcome
    confidence: ResolutionConfidence
    canonical_entity_id: UUID | None = None
    candidate_entity_ids: list[UUID] = Field(default_factory=list)


class EventResolutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: UUID
    person: MentionResolutionResult
    location: MentionResolutionResult


class DeterministicResolutionPolicy:
    version = "deterministic-exact-v1"

    def decide(
        self, mention: EntityMention, candidates: list[ResolutionCandidate]
    ) -> ResolutionDecision:
        if not candidates:
            return ResolutionDecision(
                mention_id=mention.id,
                outcome=ResolutionOutcome.UNRESOLVED,
                confidence=ResolutionConfidence.UNKNOWN,
                resolver_version=self.version,
            )
        if ResolutionFactor.EXACT_ALIAS not in candidates[0].factors:
            return ResolutionDecision(
                mention_id=mention.id,
                outcome=ResolutionOutcome.UNRESOLVED,
                confidence=ResolutionConfidence.UNKNOWN,
                candidate_entity_ids=[candidate.entity.id for candidate in candidates],
                factors=[ResolutionFactor.EMBEDDING_SIMILARITY],
                resolver_version=self.version,
            )
        highest_specificity = candidates[0].specificity
        strongest = [
            candidate for candidate in candidates if candidate.specificity == highest_specificity
        ]
        if len(strongest) > 1:
            return ResolutionDecision(
                mention_id=mention.id,
                outcome=ResolutionOutcome.AMBIGUOUS,
                confidence=ResolutionConfidence.UNKNOWN,
                candidate_entity_ids=[candidate.entity.id for candidate in strongest],
                factors=_shared_factors(strongest),
                resolver_version=self.version,
            )
        winner = strongest[0]
        return ResolutionDecision(
            mention_id=mention.id,
            outcome=ResolutionOutcome.RESOLVED,
            confidence=ResolutionConfidence.HIGH,
            canonical_entity_id=winner.entity.id,
            candidate_entity_ids=[winner.entity.id],
            factors=winner.factors,
            resolver_version=self.version,
        )


class VerifiedResolutionPolicy:
    version = "pairwise-verifier-v1"

    def decide(
        self,
        mention: EntityMention,
        candidates: list[ResolutionCandidate],
        verifications: list[PairwiseVerification],
        candidate_set_verification: CandidateSetVerification | None = None,
    ) -> ResolutionDecision:
        if not candidates:
            return ResolutionDecision(
                mention_id=mention.id,
                outcome=ResolutionOutcome.UNRESOLVED,
                confidence=ResolutionConfidence.UNKNOWN,
                resolver_version=self.version,
            )
        if ResolutionFactor.EXACT_ALIAS in candidates[0].factors:
            return DeterministicResolutionPolicy().decide(mention, candidates)
        if len(candidates) != len(verifications):
            raise ValueError("each semantic candidate requires exactly one verification")
        confirmed = [
            index
            for index, verification in enumerate(verifications)
            if verification.verdict is VerificationVerdict.SAME_ENTITY
            and not verification.insufficient_context
            and verification.confidence in (ResolutionConfidence.HIGH, ResolutionConfidence.MEDIUM)
        ]
        if len(confirmed) == 1:
            winner = candidates[confirmed[0]]
            return ResolutionDecision(
                mention_id=mention.id,
                outcome=ResolutionOutcome.RESOLVED,
                confidence=verifications[confirmed[0]].confidence,
                canonical_entity_id=winner.entity.id,
                candidate_entity_ids=[candidate.entity.id for candidate in candidates],
                factors=[ResolutionFactor.PAIRWISE_VERIFICATION, *winner.factors],
                resolver_version=self.version,
            )
        if len(confirmed) > 1 and candidate_set_verification is not None:
            selected = candidate_set_verification.selected_candidate_position
            if (
                candidate_set_verification.verdict is CandidateSetVerdict.UNIQUE_MATCH
                and selected is not None
                and selected - 1 in confirmed
                and not candidate_set_verification.insufficient_context
                and candidate_set_verification.confidence
                in (ResolutionConfidence.HIGH, ResolutionConfidence.MEDIUM)
            ):
                winner = candidates[selected - 1]
                return ResolutionDecision(
                    mention_id=mention.id,
                    outcome=ResolutionOutcome.RESOLVED,
                    confidence=candidate_set_verification.confidence,
                    canonical_entity_id=winner.entity.id,
                    candidate_entity_ids=[candidate.entity.id for candidate in candidates],
                    factors=[ResolutionFactor.PAIRWISE_VERIFICATION, *winner.factors],
                    resolver_version=self.version,
                )
            if candidate_set_verification.verdict is CandidateSetVerdict.NO_MATCH:
                return ResolutionDecision(
                    mention_id=mention.id,
                    outcome=ResolutionOutcome.UNRESOLVED,
                    confidence=ResolutionConfidence.UNKNOWN,
                    candidate_entity_ids=[candidate.entity.id for candidate in candidates],
                    factors=[ResolutionFactor.PAIRWISE_VERIFICATION],
                    resolver_version=self.version,
                )
        outcome = (
            ResolutionOutcome.AMBIGUOUS if len(confirmed) > 1 else ResolutionOutcome.UNRESOLVED
        )
        return ResolutionDecision(
            mention_id=mention.id,
            outcome=outcome,
            confidence=ResolutionConfidence.UNKNOWN,
            candidate_entity_ids=[candidate.entity.id for candidate in candidates],
            factors=[ResolutionFactor.PAIRWISE_VERIFICATION],
            resolver_version=self.version,
        )


def normalize_mention(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _shared_factors(candidates: list[ResolutionCandidate]) -> list[ResolutionFactor]:
    shared = set(candidates[0].factors)
    for candidate in candidates[1:]:
        shared.intersection_update(candidate.factors)
    return [factor for factor in ResolutionFactor if factor in shared]
