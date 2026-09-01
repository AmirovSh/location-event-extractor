from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

from location_extractor.domain import (
    CandidateOutcome,
    Certainty,
    LocationEventCandidate,
    LocationRelation,
    LocationType,
    ParsedMessage,
    ProcessResult,
    RejectionReason,
    RunStatus,
)


class Base(DeclarativeBase):
    pass


class SourceMessageRow(Base):
    __tablename__ = "source_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "external_message_id", name="uq_source_message"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    external_message_id: Mapped[str] = mapped_column(String(512))
    conversation_id: Mapped[str] = mapped_column(String(512))
    author_id: Mapped[str | None] = mapped_column(String(512))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    text_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ExtractionRunRow(Base):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        UniqueConstraint(
            "source_message_id",
            "extractor_version",
            "schema_version",
            name="uq_extraction_run_version",
        ),
        Index("ix_extraction_runs_status_created", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_messages.id", ondelete="CASCADE")
    )
    extractor_version: Mapped[str] = mapped_column(String(128))
    schema_version: Mapped[str] = mapped_column(String(64))
    extractor_provider: Mapped[str | None] = mapped_column(String(128))
    extractor_model: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    source_message: Mapped[SourceMessageRow] = relationship()
    events: Mapped[list[LocationEventRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    rejections: Mapped[list[ExtractionRejectionRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class CandidateColumns:
    person_mention: Mapped[str | None] = mapped_column(Text)
    person_reference: Mapped[str] = mapped_column(
        String(32), default="EXPLICIT", server_default="EXPLICIT"
    )
    location_mention: Mapped[str | None] = mapped_column(Text)
    location_reference: Mapped[str] = mapped_column(
        String(32), default="EXPLICIT", server_default="EXPLICIT"
    )
    relation: Mapped[str] = mapped_column(String(32))
    certainty: Mapped[str] = mapped_column(String(32))
    polarity: Mapped[str] = mapped_column(String(32), default="POSITIVE", server_default="POSITIVE")
    location_type: Mapped[str] = mapped_column(String(32))
    temporal_raw: Mapped[str | None] = mapped_column(Text)
    evidence_text: Mapped[str | None] = mapped_column(Text)
    evidence_start: Mapped[int | None] = mapped_column(Integer)
    evidence_end: Mapped[int | None] = mapped_column(Integer)
    ambiguous: Mapped[bool] = mapped_column(Boolean, default=False)
    ambiguity_reason: Mapped[str | None] = mapped_column(Text)


class LocationEventRow(CandidateColumns, Base):
    __tablename__ = "location_events"
    __table_args__ = (Index("ix_location_events_source_message", "source_message_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_messages.id", ondelete="CASCADE")
    )
    extraction_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE")
    )
    extractor_version: Mapped[str] = mapped_column(String(128))
    schema_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    run: Mapped[ExtractionRunRow] = relationship(back_populates="events")


class ExtractionRejectionRow(CandidateColumns, Base):
    __tablename__ = "extraction_rejections"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    extraction_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE")
    )
    rejection_reason: Mapped[str] = mapped_column(String(64))
    run: Mapped[ExtractionRunRow] = relationship(back_populates="rejections")


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = create_engine(database_url, pool_pre_ping=True)
    return sessionmaker(engine, expire_on_commit=False)


class SqlAlchemyLocationEventRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def get_result(
        self, message: ParsedMessage, extractor_version: str, schema_version: str
    ) -> ProcessResult | None:
        with self.sessions() as session:
            run = self._find_run(session, message, extractor_version, schema_version)
            return self._to_result(run, message.message_id) if run else None

    def save_result(
        self,
        message: ParsedMessage,
        extractor_version: str,
        schema_version: str,
        provider: str | None,
        model: str | None,
        status: RunStatus,
        outcomes: list[CandidateOutcome],
        latency_ms: int,
    ) -> ProcessResult:
        try:
            with self.sessions.begin() as session:
                source = self._get_or_create_source(session, message)
                run = ExtractionRunRow(
                    source_message_id=source.id,
                    extractor_version=extractor_version,
                    schema_version=schema_version,
                    extractor_provider=provider,
                    extractor_model=model,
                    status=status.value,
                    latency_ms=latency_ms,
                )
                session.add(run)
                session.flush()
                for outcome in outcomes:
                    values = _candidate_values(outcome.candidate)
                    if outcome.persisted:
                        run.events.append(
                            LocationEventRow(
                                **values,
                                source_message_id=source.id,
                                extractor_version=extractor_version,
                                schema_version=schema_version,
                            )
                        )
                    else:
                        run.rejections.append(
                            ExtractionRejectionRow(
                                **values,
                                rejection_reason=(
                                    outcome.rejection_reason or RejectionReason.AMBIGUOUS
                                ).value,
                            )
                        )
                session.flush()
                result = self._to_result(run, message.message_id)
            return result
        except IntegrityError:
            existing = self.get_result(message, extractor_version, schema_version)
            if existing is None:
                raise
            return existing.model_copy(update={"replayed": True})

    @staticmethod
    def _get_or_create_source(session: Session, message: ParsedMessage) -> SourceMessageRow:
        source = session.scalar(
            select(SourceMessageRow).where(
                SourceMessageRow.conversation_id == message.conversation_id,
                SourceMessageRow.external_message_id == message.message_id,
            )
        )
        if source:
            if source.text_hash != _text_hash(message.text):
                raise ValueError("message identity reused with different text")
            return source
        source = SourceMessageRow(
            external_message_id=message.message_id,
            conversation_id=message.conversation_id,
            author_id=message.author_id,
            sent_at=message.sent_at,
            text_hash=_text_hash(message.text),
        )
        session.add(source)
        session.flush()
        return source

    @staticmethod
    def _find_run(
        session: Session,
        message: ParsedMessage,
        extractor_version: str,
        schema_version: str,
    ) -> ExtractionRunRow | None:
        return session.scalar(
            select(ExtractionRunRow)
            .join(SourceMessageRow)
            .where(
                SourceMessageRow.conversation_id == message.conversation_id,
                SourceMessageRow.external_message_id == message.message_id,
                ExtractionRunRow.extractor_version == extractor_version,
                ExtractionRunRow.schema_version == schema_version,
            )
        )

    @staticmethod
    def _to_result(run: ExtractionRunRow, external_message_id: str) -> ProcessResult:
        outcomes = [
            CandidateOutcome(candidate=_to_candidate(row), persisted=True, event_id=row.id)
            for row in run.events
        ]
        outcomes.extend(
            CandidateOutcome(
                candidate=_to_candidate(row),
                persisted=False,
                rejection_reason=RejectionReason(row.rejection_reason),
            )
            for row in run.rejections
        )
        return ProcessResult(
            message_id=external_message_id, status=RunStatus(run.status), outcomes=outcomes
        )


def _candidate_values(candidate: LocationEventCandidate) -> dict[str, Any]:
    return {
        "person_mention": candidate.person_mention,
        "person_reference": candidate.person_reference.value,
        "location_mention": candidate.location_mention,
        "location_reference": candidate.location_reference.value,
        "relation": candidate.relation.value,
        "certainty": candidate.certainty.value,
        "polarity": candidate.polarity.value if candidate.polarity else "UNKNOWN",
        "location_type": candidate.location_type.value,
        "temporal_raw": candidate.temporal_raw,
        "evidence_text": candidate.evidence_text,
        "evidence_start": candidate.evidence_start,
        "evidence_end": candidate.evidence_end,
        "ambiguous": candidate.ambiguous,
        "ambiguity_reason": candidate.ambiguity_reason,
    }


def _to_candidate(row: CandidateColumns) -> LocationEventCandidate:
    return LocationEventCandidate(
        person_mention=row.person_mention,
        person_reference=row.person_reference,
        location_mention=row.location_mention,
        location_reference=row.location_reference,
        relation=LocationRelation(row.relation),
        certainty=Certainty(row.certainty),
        polarity=row.polarity,
        location_type=LocationType(row.location_type),
        temporal_raw=row.temporal_raw,
        evidence_text=row.evidence_text,
        evidence_start=row.evidence_start,
        evidence_end=row.evidence_end,
        ambiguous=row.ambiguous,
        ambiguity_reason=row.ambiguity_reason,
    )


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
