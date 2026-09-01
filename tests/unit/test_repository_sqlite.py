from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine

from location_extractor.db import (
    Base,
    SqlAlchemyLocationEventRepository,
    create_session_factory,
)
from location_extractor.domain import (
    CandidateOutcome,
    LocationEventCandidate,
    ParsedMessage,
    RunStatus,
)


def test_repository_round_trip_and_replay(tmp_path: object) -> None:
    database_url = f"sqlite:///{tmp_path}/repository.db"
    Base.metadata.create_all(create_engine(database_url))
    repository = SqlAlchemyLocationEventRepository(create_session_factory(database_url))
    message = ParsedMessage(
        conversation_id="conv",
        message_id="msg",
        sent_at=datetime.fromisoformat("2026-08-31T10:15:00+05:00"),
        text="John is in London",
    )
    candidate = LocationEventCandidate(
        person_mention="John",
        location_mention="London",
        relation="AT",
        certainty="ASSERTED",
        evidence_text="John is in London",
    )
    first = repository.save_result(
        message,
        "v1",
        "1.0",
        "fake",
        "fixture",
        RunStatus.PERSISTED,
        [CandidateOutcome(candidate=candidate, persisted=True)],
        1,
    )
    replay = repository.save_result(
        message,
        "v1",
        "1.0",
        "fake",
        "fixture",
        RunStatus.PERSISTED,
        [CandidateOutcome(candidate=candidate, persisted=True)],
        1,
    )
    assert len(first.outcomes) == 1
    assert first.outcomes[0].event_id is not None
    assert replay.replayed
    assert replay.outcomes[0].event_id == first.outcomes[0].event_id
