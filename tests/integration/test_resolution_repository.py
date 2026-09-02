from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from location_extractor.application import AlwaysPassDetector, LocationExtractionService
from location_extractor.db import SqlAlchemyLocationEventRepository, create_session_factory
from location_extractor.domain import ExtractionResult, LocationEventCandidate, ParsedMessage
from location_extractor.fakes import FakeExtractor
from location_extractor.resolution import (
    AliasSource,
    CandidateSetVerification,
    CanonicalEntity,
    EntityAlias,
    EntityMention,
    EntityType,
    PairwiseVerification,
    ResolutionCandidate,
    ResolutionScope,
)
from location_extractor.resolution_repository import SqlAlchemyEntityResolutionRepository
from location_extractor.resolution_workflow import (
    PersistedEventResolutionWorkflow,
    ResolvedLocationExtractionService,
)
from location_extractor.validation import CandidateValidator

pytestmark = pytest.mark.integration


@pytest.fixture
def postgres_resolution() -> tuple[SqlAlchemyEntityResolutionRepository, Engine]:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return SqlAlchemyEntityResolutionRepository(create_session_factory(url)), create_engine(url)


def test_postgres_scoped_resolution_schema_and_lookup(
    postgres_resolution: tuple[SqlAlchemyEntityResolutionRepository, Engine],
) -> None:
    repository, engine = postgres_resolution
    tenant_id = f"tenant-{uuid4()}"
    entity = CanonicalEntity(
        tenant_id=tenant_id,
        entity_type=EntityType.LOCATION,
        display_name="Downtown Office",
    )
    repository.save_entity(
        entity,
        [
            EntityAlias(
                canonical_entity_id=entity.id,
                alias="the office",
                scope=ResolutionScope(tenant_id=tenant_id, conversation_id="operations"),
                source=AliasSource.SEED,
            )
        ],
    )
    candidates = repository.find_candidates(
        EntityMention(
            entity_type=EntityType.LOCATION,
            text="THE OFFICE",
            scope=ResolutionScope(tenant_id=tenant_id, conversation_id="operations"),
        )
    )

    assert [candidate.entity.id for candidate in candidates] == [entity.id]
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "select count(*) from information_schema.tables "
                    "where table_schema = 'public' "
                    "and table_name in "
                    "('canonical_entities', 'entity_aliases', 'entity_mentions', "
                    "'entity_resolution_decisions')"
                )
            )
            == 4
        )


class ExactRepositoryRetriever:
    def __init__(self, repository: SqlAlchemyEntityResolutionRepository) -> None:
        self.repository = repository

    async def retrieve(self, mention: EntityMention) -> list[ResolutionCandidate]:
        return self.repository.find_candidates(mention)


class VerifierMustNotRun:
    async def verify(
        self, mention: EntityMention, candidate: ResolutionCandidate
    ) -> PairwiseVerification:
        raise AssertionError("exact aliases must bypass semantic verification")

    async def verify_candidate_set(
        self, mention: EntityMention, candidates: list[ResolutionCandidate]
    ) -> CandidateSetVerification:
        raise AssertionError("exact aliases must bypass semantic adjudication")


async def test_postgres_persisted_event_flows_into_idempotent_resolution(
    postgres_resolution: tuple[SqlAlchemyEntityResolutionRepository, Engine],
) -> None:
    repository, _ = postgres_resolution
    tenant_id = f"tenant-{uuid4()}"
    for entity_type, name in (
        (EntityType.PERSON, "Alice"),
        (EntityType.LOCATION, "Downtown Office"),
    ):
        entity = CanonicalEntity(
            tenant_id=tenant_id,
            entity_type=entity_type,
            display_name=name,
        )
        repository.save_entity(
            entity,
            [
                EntityAlias(
                    canonical_entity_id=entity.id,
                    alias=name,
                    scope=ResolutionScope(tenant_id=tenant_id),
                    source=AliasSource.SEED,
                )
            ],
        )
    text_value = "Alice is at Downtown Office."
    extraction = LocationExtractionService(
        AlwaysPassDetector(),
        FakeExtractor(
            ExtractionResult(
                events=[
                    LocationEventCandidate(
                        person_mention="Alice",
                        location_mention="Downtown Office",
                        relation="AT",
                        certainty="ASSERTED",
                        evidence_text=text_value,
                    )
                ]
            )
        ),
        CandidateValidator(),
        SqlAlchemyLocationEventRepository(repository.sessions),
        extractor_version="integration-resolution-v1",
        schema_version="1.1",
    )
    verifier = VerifierMustNotRun()
    service = ResolvedLocationExtractionService(
        extraction,
        PersistedEventResolutionWorkflow(
            repository,
            ExactRepositoryRetriever(repository),
            verifier,
            verifier,
        ),
    )
    message = ParsedMessage(
        tenant_id=tenant_id,
        conversation_id="integration-resolution",
        message_id=f"message-{uuid4()}",
        sent_at=datetime.now(UTC),
        text=text_value,
    )

    first = await service.process(message)
    second = await service.process(message)

    assert len(first.resolutions) == 1
    assert first.resolutions[0].person.outcome.value == "RESOLVED"
    assert first.resolutions[0].location.outcome.value == "RESOLVED"
    assert second.replayed
    assert second.resolutions == first.resolutions
