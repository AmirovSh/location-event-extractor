from __future__ import annotations

import asyncio
from uuid import UUID, uuid5

from location_extractor.domain import LocationEventCandidate, ParsedMessage, ProcessResult
from location_extractor.ports import (
    CandidateSetEntityVerifier,
    EntityCandidateRetriever,
    MessageProcessor,
    PairwiseEntityVerifier,
    ResolutionDecisionRepository,
)
from location_extractor.resolution import (
    EntityMention,
    EntityType,
    EventResolutionResult,
    MentionResolutionResult,
    PairwiseVerification,
    ResolutionConfidence,
    ResolutionDecision,
    ResolutionFactor,
    ResolutionScope,
    VerificationVerdict,
    VerifiedResolutionPolicy,
)

PERSON_MENTION_NAMESPACE = UUID("f23884a4-75cd-4da4-930d-2f5bd3bc18f7")
LOCATION_MENTION_NAMESPACE = UUID("b53864eb-c521-4d3c-bf5e-51aa07993586")


class PersistedEventResolutionWorkflow:
    """Resolve both mentions after an accepted event has durable provenance."""

    def __init__(
        self,
        repository: ResolutionDecisionRepository,
        retriever: EntityCandidateRetriever,
        pairwise_verifier: PairwiseEntityVerifier,
        candidate_set_verifier: CandidateSetEntityVerifier,
        *,
        verifier_concurrency: int = 2,
    ) -> None:
        if verifier_concurrency < 1:
            raise ValueError("verifier_concurrency must be positive")
        self.repository = repository
        self.retriever = retriever
        self.pairwise_verifier = pairwise_verifier
        self.candidate_set_verifier = candidate_set_verifier
        self.verifier_semaphore = asyncio.Semaphore(verifier_concurrency)
        self.policy = VerifiedResolutionPolicy()

    async def resolve_result(self, message: ParsedMessage, result: ProcessResult) -> ProcessResult:
        if result.source_message_id is None:
            raise ValueError("persisted extraction result requires source_message_id")
        resolutions: list[EventResolutionResult] = []
        for outcome in result.outcomes:
            if not outcome.persisted or outcome.event_id is None:
                continue
            candidate = outcome.candidate
            if candidate.person_mention is None or candidate.location_mention is None:
                raise ValueError("persisted event is missing explicit mentions")
            person, location = await asyncio.gather(
                self._resolve_mention(
                    _mention_for_event(
                        message,
                        result.source_message_id,
                        outcome.event_id,
                        candidate,
                        EntityType.PERSON,
                    )
                ),
                self._resolve_mention(
                    _mention_for_event(
                        message,
                        result.source_message_id,
                        outcome.event_id,
                        candidate,
                        EntityType.LOCATION,
                    )
                ),
            )
            resolutions.append(
                EventResolutionResult(event_id=outcome.event_id, person=person, location=location)
            )
        return result.model_copy(update={"resolutions": resolutions})

    async def _resolve_mention(self, mention: EntityMention) -> MentionResolutionResult:
        self.repository.save_mention(mention)
        existing = self.repository.get_active_decision(mention.id)
        if existing is not None:
            return _to_result(mention, existing)
        candidates = await self.retriever.retrieve(mention)
        if candidates and ResolutionFactor.EXACT_ALIAS in candidates[0].factors:
            decision = self.policy.decide(mention, candidates, [])
        else:

            async def verify(index: int) -> PairwiseVerification:
                async with self.verifier_semaphore:
                    return await self.pairwise_verifier.verify(mention, candidates[index])

            verifications = list(
                await asyncio.gather(*(verify(index) for index in range(len(candidates))))
            )
            confirmed = sum(
                verification.verdict is VerificationVerdict.SAME_ENTITY
                and not verification.insufficient_context
                and verification.confidence
                in (ResolutionConfidence.HIGH, ResolutionConfidence.MEDIUM)
                for verification in verifications
            )
            candidate_set_verification = None
            if confirmed > 1:
                async with self.verifier_semaphore:
                    candidate_set_verification = (
                        await self.candidate_set_verifier.verify_candidate_set(mention, candidates)
                    )
            decision = self.policy.decide(
                mention, candidates, verifications, candidate_set_verification
            )
        self.repository.save_decision(decision)
        return _to_result(mention, decision)


class ResolvedLocationExtractionService:
    def __init__(
        self, extraction_service: MessageProcessor, workflow: PersistedEventResolutionWorkflow
    ) -> None:
        self.extraction_service = extraction_service
        self.workflow = workflow

    async def process(self, message: ParsedMessage) -> ProcessResult:
        result = await self.extraction_service.process(message)
        return await self.workflow.resolve_result(message, result)


def _mention_for_event(
    message: ParsedMessage,
    source_message_id: UUID,
    event_id: UUID,
    candidate: LocationEventCandidate,
    entity_type: EntityType,
) -> EntityMention:
    is_person = entity_type is EntityType.PERSON
    text = candidate.person_mention if is_person else candidate.location_mention
    if text is None:
        raise ValueError("accepted event mention cannot be empty")
    namespace = PERSON_MENTION_NAMESPACE if is_person else LOCATION_MENTION_NAMESPACE
    return EntityMention(
        id=uuid5(namespace, str(event_id)),
        entity_type=entity_type,
        text=text,
        scope=ResolutionScope(
            tenant_id=message.tenant_id,
            source_id=message.source,
            conversation_id=message.conversation_id,
            sender_id=message.author_id,
        ),
        source_message_id=source_message_id,
        context=_bounded_context(message.text, candidate),
    )


def _bounded_context(message_text: str, candidate: LocationEventCandidate) -> str:
    if len(message_text) <= 4000:
        return message_text
    anchor = candidate.evidence_start or 0
    start = max(0, anchor - 2000)
    return message_text[start : start + 4000]


def _to_result(mention: EntityMention, decision: ResolutionDecision) -> MentionResolutionResult:
    return MentionResolutionResult(
        mention_id=mention.id,
        entity_type=mention.entity_type,
        mention_text=mention.text,
        outcome=decision.outcome,
        confidence=decision.confidence,
        canonical_entity_id=decision.canonical_entity_id,
        candidate_entity_ids=decision.candidate_entity_ids,
    )
