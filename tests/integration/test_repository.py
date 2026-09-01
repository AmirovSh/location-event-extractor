from __future__ import annotations

import os
from datetime import datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DataError

from location_extractor.db import SqlAlchemyLocationEventRepository, create_session_factory
from location_extractor.domain import (
    CandidateOutcome,
    LocationEventCandidate,
    ParsedMessage,
    ProcessResult,
    RejectionReason,
    RunStatus,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def postgres() -> tuple[SqlAlchemyLocationEventRepository, Engine]:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    engine = create_engine(url)
    return SqlAlchemyLocationEventRepository(create_session_factory(url)), engine


def message(text_value: str = "John is in London") -> ParsedMessage:
    return ParsedMessage(
        conversation_id="integration",
        message_id=f"m-{uuid4()}",
        sent_at=datetime.fromisoformat("2026-08-31T10:15:00+05:00"),
        text=text_value,
    )


def candidate(
    person: str,
    location: str,
    evidence: str,
    **updates: Any,
) -> LocationEventCandidate:
    values: dict[str, Any] = {
        "person_mention": person,
        "location_mention": location,
        "relation": "AT",
        "certainty": "ASSERTED",
        "evidence_text": evidence,
    }
    values.update(updates)
    return LocationEventCandidate(**values)


def save(
    repository: SqlAlchemyLocationEventRepository,
    parsed_message: ParsedMessage,
    status: RunStatus,
    outcomes: list[CandidateOutcome],
    *,
    provider: str = "fake",
) -> ProcessResult:
    return repository.save_result(
        parsed_message,
        "test",
        "1",
        provider,
        "fixture",
        status,
        outcomes,
        1,
    )


def test_postgres_migration_and_idempotent_accepted_event(
    postgres: tuple[SqlAlchemyLocationEventRepository, Engine],
) -> None:
    repository, engine = postgres
    with engine.connect() as connection:
        assert connection.scalar(text("select count(*) from alembic_version")) == 1

    parsed_message = message()
    accepted = candidate("John", "London", "John is in London", location_type="CITY")
    outcomes = [CandidateOutcome(candidate=accepted, persisted=True)]
    first = save(repository, parsed_message, RunStatus.PERSISTED, outcomes)
    replay = save(repository, parsed_message, RunStatus.PERSISTED, outcomes)
    loaded = repository.get_result(parsed_message, "test", "1")

    assert first.outcomes[0].event_id is not None
    assert replay.replayed is True
    assert replay.outcomes[0].event_id == first.outcomes[0].event_id
    assert loaded is not None
    assert loaded.status is RunStatus.PERSISTED
    assert loaded.outcomes[0].candidate.location_type.value == "CITY"


def test_postgres_rejected_outcome_round_trip(
    postgres: tuple[SqlAlchemyLocationEventRepository, Engine],
) -> None:
    repository, _ = postgres
    parsed_message = message("He is in London")
    rejected = candidate(
        "He",
        "London",
        "He is in London",
        person_reference="REFERENCE",
    )
    result = save(
        repository,
        parsed_message,
        RunStatus.REJECTED,
        [
            CandidateOutcome(
                candidate=rejected,
                persisted=False,
                rejection_reason=RejectionReason.UNSUPPORTED_PERSON_REFERENCE,
            )
        ],
    )
    loaded = repository.get_result(parsed_message, "test", "1")

    assert result.status is RunStatus.REJECTED
    assert loaded is not None
    assert loaded.outcomes[0].event_id is None
    assert loaded.outcomes[0].persisted is False
    assert loaded.outcomes[0].rejection_reason is RejectionReason.UNSUPPORTED_PERSON_REFERENCE


def test_postgres_multiple_and_partial_outcomes_are_atomic(
    postgres: tuple[SqlAlchemyLocationEventRepository, Engine],
) -> None:
    repository, engine = postgres
    parsed_message = message("John is in London, Mary is in Paris, and Peter is there")
    john = candidate("John", "London", "John is in London")
    mary = candidate("Mary", "Paris", "Mary is in Paris")
    peter = candidate(
        "Peter",
        "there",
        "Peter is there",
        location_reference="REFERENCE",
    )
    result = save(
        repository,
        parsed_message,
        RunStatus.PARTIAL,
        [
            CandidateOutcome(candidate=john, persisted=True),
            CandidateOutcome(candidate=mary, persisted=True),
            CandidateOutcome(
                candidate=peter,
                persisted=False,
                rejection_reason=RejectionReason.UNSUPPORTED_LOCATION_REFERENCE,
            ),
        ],
    )
    loaded = repository.get_result(parsed_message, "test", "1")

    assert result.status is RunStatus.PARTIAL
    assert loaded is not None
    assert len(loaded.outcomes) == 3
    assert sum(outcome.persisted for outcome in loaded.outcomes) == 2
    assert {outcome.candidate.person_mention for outcome in loaded.outcomes} == {
        "John",
        "Mary",
        "Peter",
    }
    with engine.connect() as connection:
        run_count = connection.scalar(
            text(
                "select count(*) from extraction_runs r "
                "join source_messages s on s.id = r.source_message_id "
                "where s.external_message_id = :message_id"
            ),
            {"message_id": parsed_message.message_id},
        )
        assert run_count == 1


def test_postgres_transaction_rolls_back_source_on_run_failure(
    postgres: tuple[SqlAlchemyLocationEventRepository, Engine],
) -> None:
    repository, engine = postgres
    parsed_message = message()
    accepted = candidate("John", "London", "John is in London")

    with pytest.raises(DataError):
        save(
            repository,
            parsed_message,
            RunStatus.PERSISTED,
            [CandidateOutcome(candidate=accepted, persisted=True)],
            provider="x" * 129,
        )

    with engine.connect() as connection:
        source_count = connection.scalar(
            text(
                "select count(*) from source_messages "
                "where conversation_id = :conversation_id "
                "and external_message_id = :message_id"
            ),
            {
                "conversation_id": parsed_message.conversation_id,
                "message_id": parsed_message.message_id,
            },
        )
        assert source_count == 0
