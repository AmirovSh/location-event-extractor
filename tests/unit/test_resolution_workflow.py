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
    EntityAlias,
    EntityMention,
    EntityType,
    PairwiseVerification,
    ResolutionCandidate,
    ResolutionConfidence,
    ResolutionDecision,
    ResolutionFactor,
    ResolutionOutcome,
    ResolutionProviderError,
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
        self.aliases: list[EntityAlias] = []

    def save_mention(self, mention: EntityMention) -> EntityMention:
        self.mentions.setdefault(mention.id, mention)
        return mention

    def get_active_decision(self, mention_id: UUID) -> ResolutionDecision | None:
        return self.decisions.get(mention_id)

    def save_decision(self, decision: ResolutionDecision) -> ResolutionDecision:
        self.decisions[decision.mention_id] = decision
        return decision

    def promote_alias(self, alias: EntityAlias) -> bool:
        if any(
            existing.normalized_alias == alias.normalized_alias and existing.scope == alias.scope
            for existing in self.aliases
        ):
            return False
        self.aliases.append(alias)
        return True


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


class FailingRetriever:
    async def retrieve(self, mention: EntityMention) -> list[ResolutionCandidate]:
        raise ResolutionProviderError("synthetic provider failure")


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
    assert len(repository.aliases) == 2
    assert all(alias.source_mention_id is not None for alias in repository.aliases)
    assert all(alias.source_resolution_id is not None for alias in repository.aliases)
    assert verifier.calls == 2


async def test_provider_failure_is_persisted_as_unresolved_for_each_mention() -> None:
    repository = FakeResolutionRepository()
    verifier = ConfirmingVerifier()
    workflow = PersistedEventResolutionWorkflow(
        repository,
        FailingRetriever(),
        verifier,
        verifier,
    )

    result = await workflow.resolve_result(
        ParsedMessage(
            tenant_id="tenant-alpha",
            conversation_id="conv-ops",
            message_id="msg-provider-failure",
            author_id="sender-1",
            sent_at=datetime.now(UTC),
            text="John is at the central branch.",
        ),
        await FakeExtractionService().process(
            ParsedMessage(
                tenant_id="tenant-alpha",
                conversation_id="conv-ops",
                message_id="msg-provider-failure",
                author_id="sender-1",
                sent_at=datetime.now(UTC),
                text="John is at the central branch.",
            )
        ),
    )

    assert len(result.resolutions) == 1
    assert result.resolutions[0].person.outcome is ResolutionOutcome.UNRESOLVED
    assert result.resolutions[0].location.outcome is ResolutionOutcome.UNRESOLVED
    assert len(repository.aliases) == 0
