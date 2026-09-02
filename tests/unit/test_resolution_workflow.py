from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from location_extractor.domain import (
    CandidateOutcome,
    LocationEventCandidate,
    ParsedMessage,
    ProcessResult,
    RunStatus,
)
from location_extractor.resolution import (
    CandidateSetVerification,
    CanonicalEntity,
    EntityMention,
    EntityType,
    PairwiseVerification,
    ResolutionCandidate,
    ResolutionConfidence,
    ResolutionDecision,
    ResolutionFactor,
    ResolutionOutcome,
    VerificationVerdict,
)
from location_extractor.resolution_workflow import (
    PersistedEventResolutionWorkflow,
    ResolvedLocationExtractionService,
)


class FakeResolutionRepository:
    def __init__(self) -> None:
        self.mentions: dict[UUID, EntityMention] = {}
        self.decisions: dict[UUID, ResolutionDecision] = {}

    def save_mention(self, mention: EntityMention) -> EntityMention:
        self.mentions.setdefault(mention.id, mention)
        return mention

    def get_active_decision(self, mention_id: UUID) -> ResolutionDecision | None:
        return self.decisions.get(mention_id)

    def save_decision(self, decision: ResolutionDecision) -> ResolutionDecision:
        self.decisions[decision.mention_id] = decision
        return decision


class FakeRetriever:
    async def retrieve(self, mention: EntityMention) -> list[ResolutionCandidate]:
        entity_id = UUID(int=1 if mention.entity_type is EntityType.PERSON else 2)
        return [
            ResolutionCandidate(
                entity=CanonicalEntity(
                    id=entity_id,
                    tenant_id=mention.scope.tenant_id,
                    entity_type=mention.entity_type,
                    display_name="John Smith"
                    if mention.entity_type is EntityType.PERSON
                    else "Downtown Office",
                ),
                matched_alias=mention.text,
                supporting_texts=[mention.text],
                factors=[ResolutionFactor.EMBEDDING_SIMILARITY],
                specificity=0,
                similarity=0.9,
            )
        ]


class ConfirmingVerifier:
    def __init__(self) -> None:
        self.calls = 0

    async def verify(
        self, mention: EntityMention, candidate: ResolutionCandidate
    ) -> PairwiseVerification:
        self.calls += 1
        return PairwiseVerification(
            verdict=VerificationVerdict.SAME_ENTITY,
            confidence=ResolutionConfidence.HIGH,
            insufficient_context=False,
        )

    async def verify_candidate_set(
        self, mention: EntityMention, candidates: list[ResolutionCandidate]
    ) -> CandidateSetVerification:
        raise AssertionError("one confirmed candidate does not need adjudication")


class FakeExtractionService:
    async def process(self, message: ParsedMessage) -> ProcessResult:
        return ProcessResult(
            message_id=message.message_id,
            source_message_id=UUID(int=10),
            status=RunStatus.PERSISTED,
            outcomes=[
                CandidateOutcome(
                    candidate=LocationEventCandidate(
                        person_mention="John from operations",
                        location_mention="central branch",
                        relation="AT",
                        certainty="ASSERTED",
                        evidence_text=message.text,
                    ),
                    persisted=True,
                    event_id=UUID(int=20),
                )
            ],
        )


async def test_persisted_event_is_resolved_and_replay_reuses_decisions() -> None:
    repository = FakeResolutionRepository()
    verifier = ConfirmingVerifier()
    workflow = PersistedEventResolutionWorkflow(
        repository,
        FakeRetriever(),
        verifier,
        verifier,
    )
    service = ResolvedLocationExtractionService(FakeExtractionService(), workflow)
    message = ParsedMessage(
        tenant_id="tenant-alpha",
        conversation_id="conv-ops",
        message_id="msg-1",
        author_id="sender-1",
        sent_at=datetime.now(UTC),
        text="John from operations is at the central branch.",
    )

    first = await service.process(message)
    second = await service.process(message)

    assert len(first.resolutions) == 1
    assert first.resolutions[0].person.canonical_entity_id == UUID(int=1)
    assert first.resolutions[0].location.canonical_entity_id == UUID(int=2)
    assert all(
        result.outcome is ResolutionOutcome.RESOLVED
        for result in (first.resolutions[0].person, first.resolutions[0].location)
    )
    assert second.resolutions == first.resolutions
    assert len(repository.mentions) == 2
    assert len(repository.decisions) == 2
    assert verifier.calls == 2
