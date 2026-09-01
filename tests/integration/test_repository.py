from __future__ import annotations

import os
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from location_extractor.db import SqlAlchemyLocationEventRepository, create_session_factory
from location_extractor.domain import (
    CandidateOutcome,
    LocationEventCandidate,
    ParsedMessage,
    RunStatus,
)

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")
def test_postgres_migration_and_idempotent_repository() -> None:
    url = os.environ["TEST_DATABASE_URL"]
    engine = create_engine(url)
    with engine.connect() as connection:
        assert connection.scalar(text("select count(*) from alembic_version")) == 1
    repo = SqlAlchemyLocationEventRepository(create_session_factory(url))
    message = ParsedMessage(
        conversation_id="integration",
        message_id=f"m-{uuid4()}",
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
    first = repo.save_result(
        message,
        "test",
        "1",
        "fake",
        "fixture",
        RunStatus.PERSISTED,
        [CandidateOutcome(candidate=candidate, persisted=True)],
        1,
    )
    second = repo.save_result(
        message,
        "test",
        "1",
        "fake",
        "fixture",
        RunStatus.PERSISTED,
        [CandidateOutcome(candidate=candidate, persisted=True)],
        1,
    )
    assert first.outcomes[0].event_id == second.outcomes[0].event_id
    assert second.replayed
