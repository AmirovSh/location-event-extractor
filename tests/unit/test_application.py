from __future__ import annotations

from datetime import datetime

from location_extractor.application import AlwaysPassDetector, LocationExtractionService
from location_extractor.domain import (
    ExtractionResult,
    LocationEventCandidate,
    ParsedMessage,
    RunStatus,
)
from location_extractor.fakes import FakeExtractor, InMemoryRepository
from location_extractor.validation import CandidateValidator


def make_message() -> ParsedMessage:
    return ParsedMessage(
        conversation_id="conv-42",
        message_id="msg-1001",
        author_id="user-5",
        sent_at=datetime.fromisoformat("2026-08-31T10:15:00+05:00"),
        text="John is in London, and Mary is in Paris.",
    )


def make_service(result: ExtractionResult) -> tuple[LocationExtractionService, FakeExtractor]:
    extractor = FakeExtractor(result)
    service = LocationExtractionService(
        AlwaysPassDetector(),
        extractor,
        CandidateValidator(),
        InMemoryRepository(),
        extractor_version="test-1",
        schema_version="1.0",
    )
    return service, extractor


async def test_multiple_candidates_and_idempotent_replay() -> None:
    service, extractor = make_service(
        ExtractionResult(
            events=[
                LocationEventCandidate(
                    person_mention="John",
                    location_mention="London",
                    relation="AT",
                    certainty="ASSERTED",
                    evidence_text="John is in London",
                ),
                LocationEventCandidate(
                    person_mention="Mary",
                    location_mention="Paris",
                    relation="AT",
                    certainty="ASSERTED",
                    evidence_text="Mary is in Paris",
                ),
            ]
        )
    )
    first = await service.process(make_message())
    second = await service.process(make_message())
    assert first.status is RunStatus.PERSISTED
    assert len(first.outcomes) == 2
    assert all(outcome.event_id for outcome in first.outcomes)
    assert second.replayed is True
    assert [item.event_id for item in second.outcomes] == [item.event_id for item in first.outcomes]
    assert len(extractor.calls) == 1


async def test_rejected_candidate_is_not_persisted() -> None:
    service, _ = make_service(
        ExtractionResult(
            events=[
                LocationEventCandidate(
                    person_mention="He",
                    person_reference="REFERENCE",
                    location_mention="London",
                    relation="AT",
                    evidence_text="John is in London",
                )
            ]
        )
    )
    result = await service.process(make_message())
    assert result.status is RunStatus.REJECTED
    assert result.outcomes[0].persisted is False
    assert result.outcomes[0].event_id is None


async def test_empty_extraction_is_no_event() -> None:
    service, _ = make_service(ExtractionResult())
    result = await service.process(make_message())
    assert result.status is RunStatus.NO_EVENT
