from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from location_extractor.resolution import EventResolutionResult


class LocationRelation(StrEnum):
    AT = "AT"
    TO = "TO"
    FROM = "FROM"
    LEFT = "LEFT"
    ARRIVED = "ARRIVED"
    NEAR = "NEAR"
    UNKNOWN = "UNKNOWN"


class Certainty(StrEnum):
    ASSERTED = "ASSERTED"
    PROBABLE = "PROBABLE"
    POSSIBLE = "POSSIBLE"
    NEGATED = "NEGATED"
    PLANNED = "PLANNED"
    UNKNOWN = "UNKNOWN"


class LocationType(StrEnum):
    COUNTRY = "COUNTRY"
    CITY = "CITY"
    DISTRICT = "DISTRICT"
    STREET = "STREET"
    ADDRESS = "ADDRESS"
    BUILDING = "BUILDING"
    OFFICE = "OFFICE"
    HOME = "HOME"
    VENUE = "VENUE"
    AIRPORT = "AIRPORT"
    STATION = "STATION"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class MentionReference(StrEnum):
    EXPLICIT = "EXPLICIT"
    REFERENCE = "REFERENCE"
    UNKNOWN = "UNKNOWN"


class Polarity(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    UNKNOWN = "UNKNOWN"


class RejectionReason(StrEnum):
    MISSING_PERSON = "MISSING_PERSON"
    MISSING_LOCATION = "MISSING_LOCATION"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    EVIDENCE_MISMATCH = "EVIDENCE_MISMATCH"
    INVALID_EVIDENCE_SPAN = "INVALID_EVIDENCE_SPAN"
    AMBIGUOUS = "AMBIGUOUS"
    UNSUPPORTED_PERSON_REFERENCE = "UNSUPPORTED_PERSON_REFERENCE"
    UNSUPPORTED_LOCATION_REFERENCE = "UNSUPPORTED_LOCATION_REFERENCE"
    UNKNOWN_RELATION = "UNKNOWN_RELATION"
    CERTAINTY_CONFLICT = "CERTAINTY_CONFLICT"


class RunStatus(StrEnum):
    PERSISTED = "PERSISTED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    NO_EVENT = "NO_EVENT"


class ParsedMessage(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    tenant_id: str = Field(default="default", min_length=1, max_length=512)
    conversation_id: str = Field(min_length=1, max_length=512)
    message_id: str = Field(min_length=1, max_length=512)
    author_id: str | None = Field(default=None, max_length=512)
    sent_at: datetime
    text: str = Field(min_length=1, max_length=50_000)
    source: str | None = Field(default=None, max_length=128)
    locale: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def require_timezone(self) -> ParsedMessage:
        if self.sent_at.tzinfo is None or self.sent_at.utcoffset() is None:
            raise ValueError("sent_at must include a timezone")
        return self


class LocationEventCandidate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    person_mention: str | None = None
    person_reference: MentionReference = MentionReference.EXPLICIT
    location_mention: str | None = None
    location_reference: MentionReference = MentionReference.EXPLICIT
    relation: LocationRelation = LocationRelation.UNKNOWN
    certainty: Certainty = Certainty.UNKNOWN
    polarity: Polarity | None = None
    location_type: LocationType = LocationType.UNKNOWN
    temporal_raw: str | None = None
    evidence_text: str | None = None
    evidence_start: int | None = Field(default=None, ge=0)
    evidence_end: int | None = Field(default=None, ge=0)
    ambiguous: bool = False
    ambiguity_reason: str | None = None

    @model_validator(mode="after")
    def default_legacy_polarity(self) -> LocationEventCandidate:
        if self.polarity is None:
            self.polarity = (
                Polarity.NEGATIVE if self.certainty is Certainty.NEGATED else Polarity.POSITIVE
            )
        return self


class ExtractionResult(BaseModel):
    events: list[LocationEventCandidate] = Field(default_factory=list)


class LocationEvent(BaseModel):
    id: UUID
    source_message_id: UUID
    person_mention: str
    location_mention: str
    relation: LocationRelation
    certainty: Certainty
    location_type: LocationType
    temporal_raw: str | None
    evidence_text: str
    evidence_start: int | None
    evidence_end: int | None
    extractor_version: str
    schema_version: str
    created_at: datetime


class ValidationResult(BaseModel):
    accepted: bool
    candidate: LocationEventCandidate
    reason: RejectionReason | None = None


class CandidateOutcome(BaseModel):
    candidate: LocationEventCandidate
    persisted: bool
    event_id: UUID | None = None
    rejection_reason: RejectionReason | None = None


class ProcessResult(BaseModel):
    message_id: str
    source_message_id: UUID | None = None
    status: RunStatus
    outcomes: list[CandidateOutcome]
    resolutions: list[EventResolutionResult] = Field(default_factory=list)
    replayed: bool = False
