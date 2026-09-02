from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from location_extractor.db import Base, create_session_factory
from location_extractor.resolution import (
    AliasSource,
    CanonicalEntity,
    ControlledAliasPromotionPolicy,
    DeterministicResolutionPolicy,
    EntityAlias,
    EntityMention,
    EntityType,
    ResolutionConfidence,
    ResolutionDecision,
    ResolutionFactor,
    ResolutionOutcome,
    ResolutionScope,
    normalize_mention,
)
from location_extractor.resolution_evaluation import (
    evaluate_resolution_dataset,
    load_resolution_dataset,
    seed_resolution_dataset,
)
from location_extractor.resolution_repository import SqlAlchemyEntityResolutionRepository

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "resolution_cases.json"


@pytest.fixture
def repository(tmp_path: Path) -> SqlAlchemyEntityResolutionRepository:
    database_url = f"sqlite:///{tmp_path}/resolution.db"
    Base.metadata.create_all(create_engine(database_url))
    return SqlAlchemyEntityResolutionRepository(create_session_factory(database_url))


def test_resolution_dataset_drives_scoped_candidate_retrieval(
    repository: SqlAlchemyEntityResolutionRepository,
) -> None:
    dataset = load_resolution_dataset(FIXTURE_PATH)
    seed_resolution_dataset(repository, dataset)
    report = evaluate_resolution_dataset(repository, DeterministicResolutionPolicy(), dataset)

    assert report.case_count == 24
    assert report.tenant_leakage_count == 0
    assert report.entity_type_leakage_count == 0
    assert report.metrics.resolved_precision == 1
    assert report.metrics.candidate_recall_at_3 < 1
    semantic_results = {result.name: result for result in report.cases if "needs" in result.name}
    assert semantic_results
    assert all(
        result.predicted_outcome is ResolutionOutcome.UNRESOLVED
        for result in semantic_results.values()
    )


def test_normalization_is_generic_and_language_independent() -> None:
    assert normalize_mention("  Downtown\t OFFICE ") == "downtown office"
    assert normalize_mention("Ａｌｉｃｅ") == "alice"


def test_resolution_report_omits_mentions_and_context(
    repository: SqlAlchemyEntityResolutionRepository,
) -> None:
    dataset = load_resolution_dataset(FIXTURE_PATH)
    seed_resolution_dataset(repository, dataset)
    report = evaluate_resolution_dataset(repository, DeterministicResolutionPolicy(), dataset)

    serialized = report.model_dump_json()
    assert "central branch" not in serialized
    assert "Emma is working" not in serialized


def test_repository_rejects_cross_tenant_alias(
    repository: SqlAlchemyEntityResolutionRepository,
) -> None:
    entity = CanonicalEntity(
        tenant_id="tenant-a",
        entity_type=EntityType.PERSON,
        display_name="Alice",
    )
    alias = EntityAlias(
        canonical_entity_id=entity.id,
        alias="Alice",
        scope=ResolutionScope(tenant_id="tenant-b"),
        source=AliasSource.SEED,
    )

    with pytest.raises(ValueError, match="same tenant"):
        repository.save_entity(entity, [alias])


def test_resolution_decisions_are_superseded_instead_of_overwritten(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path}/decisions.db"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    repository = SqlAlchemyEntityResolutionRepository(create_session_factory(database_url))
    scope = ResolutionScope(tenant_id="tenant-a")
    entity = CanonicalEntity(
        tenant_id=scope.tenant_id,
        entity_type=EntityType.LOCATION,
        display_name="Downtown Office",
    )
    repository.save_entity(entity, [])
    mention = repository.save_mention(
        EntityMention(entity_type=EntityType.LOCATION, text="the office", scope=scope)
    )
    first = repository.save_decision(
        ResolutionDecision(
            mention_id=mention.id,
            outcome=ResolutionOutcome.UNRESOLVED,
            confidence=ResolutionConfidence.UNKNOWN,
            resolver_version="v1",
        )
    )
    repository.save_decision(
        ResolutionDecision(
            mention_id=mention.id,
            outcome=ResolutionOutcome.RESOLVED,
            confidence=ResolutionConfidence.HIGH,
            canonical_entity_id=entity.id,
            candidate_entity_ids=[entity.id],
            resolver_version="v2",
            supersedes_resolution_id=first.id,
        )
    )

    with engine.connect() as connection:
        decisions = connection.execute(
            text("select outcome, active from entity_resolution_decisions order by created_at")
        ).all()
    assert decisions == [("UNRESOLVED", 0), ("RESOLVED", 1)]


def test_resolution_decision_cannot_cross_tenant_boundary(
    repository: SqlAlchemyEntityResolutionRepository,
) -> None:
    entity = CanonicalEntity(
        tenant_id="tenant-b",
        entity_type=EntityType.PERSON,
        display_name="Alice",
    )
    repository.save_entity(entity, [])
    mention = repository.save_mention(
        EntityMention(
            entity_type=EntityType.PERSON,
            text="Alice",
            scope=ResolutionScope(tenant_id="tenant-a"),
        )
    )

    with pytest.raises(ValueError, match="tenant and type"):
        repository.save_decision(
            ResolutionDecision(
                mention_id=mention.id,
                outcome=ResolutionOutcome.RESOLVED,
                confidence=ResolutionConfidence.HIGH,
                canonical_entity_id=entity.id,
                resolver_version="v1",
            )
        )


def test_controlled_alias_promotion_is_scoped_idempotent_and_provenanced(
    repository: SqlAlchemyEntityResolutionRepository,
) -> None:
    scope = ResolutionScope(
        tenant_id="tenant-a",
        source_id="chat",
        conversation_id="operations",
        sender_id="dispatcher",
    )
    entity = CanonicalEntity(
        tenant_id=scope.tenant_id,
        entity_type=EntityType.PERSON,
        display_name="John Smith",
    )
    repository.save_entity(entity, [])
    mention = repository.save_mention(
        EntityMention(entity_type=EntityType.PERSON, text="John S.", scope=scope)
    )
    decision = repository.save_decision(
        ResolutionDecision(
            mention_id=mention.id,
            outcome=ResolutionOutcome.RESOLVED,
            confidence=ResolutionConfidence.HIGH,
            canonical_entity_id=entity.id,
            candidate_entity_ids=[entity.id],
            factors=[ResolutionFactor.PAIRWISE_VERIFICATION],
            resolver_version="test-v1",
        )
    )
    alias = ControlledAliasPromotionPolicy().propose(mention, decision)

    assert alias is not None
    with pytest.raises(ValueError, match="eligible resolution"):
        repository.promote_alias(alias.model_copy(update={"alias": "Unverified Name"}))
    assert repository.promote_alias(alias)
    assert not repository.promote_alias(alias)
    candidates = repository.find_candidates(
        EntityMention(entity_type=EntityType.PERSON, text="john s.", scope=scope)
    )
    assert [candidate.entity.id for candidate in candidates] == [entity.id]
    assert alias.source_mention_id == mention.id
    assert alias.source_resolution_id == decision.id


def test_alias_promotion_rejects_medium_confidence_and_exact_alias() -> None:
    scope = ResolutionScope(tenant_id="tenant-a")
    mention = EntityMention(entity_type=EntityType.PERSON, text="John", scope=scope)
    policy = ControlledAliasPromotionPolicy()
    medium = ResolutionDecision(
        mention_id=mention.id,
        outcome=ResolutionOutcome.RESOLVED,
        confidence=ResolutionConfidence.MEDIUM,
        canonical_entity_id=CanonicalEntity(
            tenant_id=scope.tenant_id,
            entity_type=EntityType.PERSON,
            display_name="John Smith",
        ).id,
        factors=[ResolutionFactor.PAIRWISE_VERIFICATION],
        resolver_version="test-v1",
    )
    exact = medium.model_copy(
        update={
            "confidence": ResolutionConfidence.HIGH,
            "factors": [ResolutionFactor.EXACT_ALIAS],
        }
    )

    assert policy.propose(mention, medium) is None
    assert policy.propose(mention, exact) is None
