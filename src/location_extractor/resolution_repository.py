from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.orm import Mapped, Session, joinedload, mapped_column, relationship, sessionmaker

from location_extractor.db import Base
from location_extractor.resolution import (
    CanonicalEntity,
    EmbeddingCandidateDocument,
    EntityAlias,
    EntityMention,
    EntityType,
    ResolutionCandidate,
    ResolutionDecision,
    ResolutionFactor,
    ResolutionScope,
)


class CanonicalEntityRow(Base):
    __tablename__ = "canonical_entities"
    __table_args__ = (Index("ix_canonical_entities_tenant_type", "tenant_id", "entity_type"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(512))
    entity_type: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    aliases: Mapped[list[EntityAliasRow]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )


class EntityAliasRow(Base):
    __tablename__ = "entity_aliases"
    __table_args__ = (
        Index(
            "ix_entity_aliases_lookup",
            "tenant_id",
            "entity_type",
            "normalized_alias",
            "active",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    canonical_entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_entities.id", ondelete="CASCADE")
    )
    tenant_id: Mapped[str] = mapped_column(String(512))
    entity_type: Mapped[str] = mapped_column(String(32))
    alias: Mapped[str] = mapped_column(Text)
    normalized_alias: Mapped[str] = mapped_column(Text)
    source_id: Mapped[str | None] = mapped_column(String(512))
    conversation_id: Mapped[str | None] = mapped_column(String(512))
    sender_id: Mapped[str | None] = mapped_column(String(512))
    alias_source: Mapped[str] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entity: Mapped[CanonicalEntityRow] = relationship(back_populates="aliases")


class EntityMentionRow(Base):
    __tablename__ = "entity_mentions"
    __table_args__ = (
        Index("ix_entity_mentions_scope", "tenant_id", "source_id", "conversation_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32))
    mention_text: Mapped[str] = mapped_column(Text)
    normalized_mention: Mapped[str] = mapped_column(Text)
    tenant_id: Mapped[str] = mapped_column(String(512))
    source_id: Mapped[str | None] = mapped_column(String(512))
    conversation_id: Mapped[str | None] = mapped_column(String(512))
    sender_id: Mapped[str | None] = mapped_column(String(512))
    source_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_messages.id", ondelete="SET NULL")
    )
    context_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EntityResolutionDecisionRow(Base):
    __tablename__ = "entity_resolution_decisions"
    __table_args__ = (
        Index(
            "ux_entity_resolution_decisions_active_mention",
            "mention_id",
            unique=True,
            postgresql_where=text("active"),
            sqlite_where=text("active"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    mention_id: Mapped[UUID] = mapped_column(ForeignKey("entity_mentions.id", ondelete="CASCADE"))
    outcome: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[str] = mapped_column(String(32))
    canonical_entity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("canonical_entities.id", ondelete="RESTRICT")
    )
    candidate_entity_ids: Mapped[list[str]] = mapped_column(JSON)
    factors: Mapped[list[str]] = mapped_column(JSON)
    resolver_version: Mapped[str] = mapped_column(String(128))
    active: Mapped[bool] = mapped_column(Boolean)
    supersedes_resolution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("entity_resolution_decisions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SqlAlchemyEntityResolutionRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def save_entity(self, entity: CanonicalEntity, aliases: list[EntityAlias]) -> CanonicalEntity:
        if any(alias.canonical_entity_id != entity.id for alias in aliases):
            raise ValueError("alias must reference the saved entity")
        if any(alias.scope.tenant_id != entity.tenant_id for alias in aliases):
            raise ValueError("alias and entity must belong to the same tenant")
        with self.sessions.begin() as session:
            existing = session.get(CanonicalEntityRow, entity.id)
            if existing is not None:
                if (
                    existing.tenant_id != entity.tenant_id
                    or existing.entity_type != entity.entity_type.value
                    or existing.display_name != entity.display_name
                ):
                    raise ValueError("entity id reused with different canonical data")
                return entity
            row = CanonicalEntityRow(
                id=entity.id,
                tenant_id=entity.tenant_id,
                entity_type=entity.entity_type.value,
                display_name=entity.display_name,
                created_at=entity.created_at,
            )
            session.add(row)
            row.aliases.extend(_alias_row(alias, entity.entity_type) for alias in aliases)
        return entity

    def save_mention(self, mention: EntityMention) -> EntityMention:
        with self.sessions.begin() as session:
            existing = session.get(EntityMentionRow, mention.id)
            if existing is not None:
                if (
                    existing.tenant_id != mention.scope.tenant_id
                    or existing.entity_type != mention.entity_type.value
                    or existing.normalized_mention != mention.normalized_text
                    or existing.source_message_id != mention.source_message_id
                ):
                    raise ValueError("mention id reused with different resolution data")
                return mention
            session.add(
                EntityMentionRow(
                    id=mention.id,
                    entity_type=mention.entity_type.value,
                    mention_text=mention.text,
                    normalized_mention=mention.normalized_text,
                    tenant_id=mention.scope.tenant_id,
                    source_id=mention.scope.source_id,
                    conversation_id=mention.scope.conversation_id,
                    sender_id=mention.scope.sender_id,
                    source_message_id=mention.source_message_id,
                    context_hash=mention.context_hash,
                    created_at=mention.created_at,
                )
            )
        return mention

    def get_active_decision(self, mention_id: UUID) -> ResolutionDecision | None:
        with self.sessions() as session:
            row = session.scalar(
                select(EntityResolutionDecisionRow).where(
                    EntityResolutionDecisionRow.mention_id == mention_id,
                    EntityResolutionDecisionRow.active.is_(True),
                )
            )
            return _to_decision(row) if row is not None else None

    def find_candidates(
        self, mention: EntityMention, *, limit: int = 10
    ) -> list[ResolutionCandidate]:
        if limit < 1:
            raise ValueError("limit must be positive")
        scope = mention.scope
        with self.sessions() as session:
            rows = session.scalars(
                select(EntityAliasRow)
                .join(CanonicalEntityRow)
                .options(joinedload(EntityAliasRow.entity))
                .where(
                    EntityAliasRow.tenant_id == scope.tenant_id,
                    EntityAliasRow.entity_type == mention.entity_type.value,
                    EntityAliasRow.normalized_alias == mention.normalized_text,
                    EntityAliasRow.active.is_(True),
                    _scope_match(EntityAliasRow.source_id, scope.source_id),
                    _scope_match(EntityAliasRow.conversation_id, scope.conversation_id),
                    _scope_match(EntityAliasRow.sender_id, scope.sender_id),
                )
            ).all()
            best_by_entity: dict[UUID, ResolutionCandidate] = {}
            for row in rows:
                candidate = _to_candidate(row, scope)
                existing = best_by_entity.get(row.canonical_entity_id)
                if existing is None or candidate.specificity > existing.specificity:
                    best_by_entity[row.canonical_entity_id] = candidate
            return sorted(
                best_by_entity.values(),
                key=lambda candidate: (-candidate.specificity, str(candidate.entity.id)),
            )[:limit]

    def list_embedding_documents(
        self, mention: EntityMention, *, limit: int = 1000
    ) -> list[EmbeddingCandidateDocument]:
        if limit < 1:
            raise ValueError("limit must be positive")
        scope = mention.scope
        with self.sessions() as session:
            rows = session.scalars(
                select(EntityAliasRow)
                .join(CanonicalEntityRow)
                .options(joinedload(EntityAliasRow.entity))
                .where(
                    EntityAliasRow.tenant_id == scope.tenant_id,
                    EntityAliasRow.entity_type == mention.entity_type.value,
                    EntityAliasRow.active.is_(True),
                    _scope_match(EntityAliasRow.source_id, scope.source_id),
                    _scope_match(EntityAliasRow.conversation_id, scope.conversation_id),
                    _scope_match(EntityAliasRow.sender_id, scope.sender_id),
                )
                .order_by(EntityAliasRow.canonical_entity_id, EntityAliasRow.id)
            ).all()
            grouped: dict[UUID, tuple[CanonicalEntityRow, list[EntityAliasRow]]] = {}
            for row in rows:
                if row.canonical_entity_id not in grouped:
                    grouped[row.canonical_entity_id] = (row.entity, [])
                grouped[row.canonical_entity_id][1].append(row)

            documents = [
                _to_embedding_document(entity, aliases, scope)
                for entity, aliases in grouped.values()
            ]
            return sorted(
                documents,
                key=lambda document: (-document.specificity, str(document.entity.id)),
            )[:limit]

    def save_decision(self, decision: ResolutionDecision) -> ResolutionDecision:
        with self.sessions.begin() as session:
            mention = session.get(EntityMentionRow, decision.mention_id)
            if mention is None:
                raise ValueError("resolution mention does not exist")
            entity_ids = set(decision.candidate_entity_ids)
            if decision.canonical_entity_id is not None:
                entity_ids.add(decision.canonical_entity_id)
            entities = list(
                session.scalars(
                    select(CanonicalEntityRow).where(CanonicalEntityRow.id.in_(entity_ids))
                )
            )
            if len(entities) != len(entity_ids):
                raise ValueError("resolution references an unknown canonical entity")
            if any(
                entity.tenant_id != mention.tenant_id or entity.entity_type != mention.entity_type
                for entity in entities
            ):
                raise ValueError("resolution entity must match mention tenant and type")
            if decision.supersedes_resolution_id is not None:
                result = session.execute(
                    update(EntityResolutionDecisionRow)
                    .where(
                        EntityResolutionDecisionRow.id == decision.supersedes_resolution_id,
                        EntityResolutionDecisionRow.mention_id == decision.mention_id,
                        EntityResolutionDecisionRow.active.is_(True),
                    )
                    .values(active=False)
                )
                changed = getattr(result, "rowcount", 0)
                if changed != 1:
                    raise ValueError("superseded resolution is not active for this mention")
            session.add(
                EntityResolutionDecisionRow(
                    id=decision.id,
                    mention_id=decision.mention_id,
                    outcome=decision.outcome.value,
                    confidence=decision.confidence.value,
                    canonical_entity_id=decision.canonical_entity_id,
                    candidate_entity_ids=[str(value) for value in decision.candidate_entity_ids],
                    factors=[value.value for value in decision.factors],
                    resolver_version=decision.resolver_version,
                    active=decision.active,
                    supersedes_resolution_id=decision.supersedes_resolution_id,
                    created_at=decision.created_at,
                )
            )
        return decision


def _scope_match(column: Any, value: str | None) -> Any:
    return or_(column.is_(None), column == value)


def register_resolution_models() -> None:
    """Import target used by Alembic to register these rows on Base.metadata."""


def _alias_row(alias: EntityAlias, entity_type: EntityType) -> EntityAliasRow:
    return EntityAliasRow(
        id=alias.id,
        canonical_entity_id=alias.canonical_entity_id,
        tenant_id=alias.scope.tenant_id,
        entity_type=entity_type.value,
        alias=alias.alias,
        normalized_alias=alias.normalized_alias,
        source_id=alias.scope.source_id,
        conversation_id=alias.scope.conversation_id,
        sender_id=alias.scope.sender_id,
        alias_source=alias.source.value,
        active=alias.active,
        created_at=alias.created_at,
    )


def _to_candidate(row: EntityAliasRow, scope: ResolutionScope) -> ResolutionCandidate:
    factors, specificity = _scope_factors(row, scope)
    factors.insert(0, ResolutionFactor.EXACT_ALIAS)
    return ResolutionCandidate(
        entity=_to_entity(row.entity),
        matched_alias=row.alias,
        factors=factors,
        specificity=specificity,
    )


def _to_embedding_document(
    entity: CanonicalEntityRow,
    aliases: list[EntityAliasRow],
    scope: ResolutionScope,
) -> EmbeddingCandidateDocument:
    best_factors = [ResolutionFactor.SAME_TENANT]
    best_specificity = 0
    for alias in aliases:
        factors, specificity = _scope_factors(alias, scope)
        if specificity > best_specificity:
            best_factors = factors
            best_specificity = specificity
    return EmbeddingCandidateDocument(
        entity=_to_entity(entity),
        texts=[entity.display_name, *(alias.alias for alias in aliases)],
        factors=best_factors,
        specificity=best_specificity,
    )


def _scope_factors(
    row: EntityAliasRow, scope: ResolutionScope
) -> tuple[list[ResolutionFactor], int]:
    factors = [ResolutionFactor.SAME_TENANT]
    specificity = 0
    for scoped_value, current_value, factor in (
        (row.source_id, scope.source_id, ResolutionFactor.SAME_SOURCE),
        (row.conversation_id, scope.conversation_id, ResolutionFactor.SAME_CONVERSATION),
        (row.sender_id, scope.sender_id, ResolutionFactor.SAME_SENDER),
    ):
        if scoped_value is not None and scoped_value == current_value:
            factors.append(factor)
            specificity += 1
    return factors, specificity


def _to_entity(row: CanonicalEntityRow) -> CanonicalEntity:
    return CanonicalEntity(
        id=row.id,
        tenant_id=row.tenant_id,
        entity_type=EntityType(row.entity_type),
        display_name=row.display_name,
        created_at=row.created_at,
    )


def _to_decision(row: EntityResolutionDecisionRow) -> ResolutionDecision:
    return ResolutionDecision(
        id=row.id,
        mention_id=row.mention_id,
        outcome=row.outcome,
        confidence=row.confidence,
        canonical_entity_id=row.canonical_entity_id,
        candidate_entity_ids=[UUID(value) for value in row.candidate_entity_ids],
        factors=row.factors,
        resolver_version=row.resolver_version,
        active=row.active,
        supersedes_resolution_id=row.supersedes_resolution_id,
        created_at=row.created_at,
    )
