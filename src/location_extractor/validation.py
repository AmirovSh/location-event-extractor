from __future__ import annotations

from dataclasses import dataclass

from location_extractor.domain import (
    Certainty,
    LocationEventCandidate,
    LocationRelation,
    MentionReference,
    ParsedMessage,
    Polarity,
    RejectionReason,
    ValidationResult,
)


@dataclass(frozen=True)
class CandidateEvidence:
    source_text: str
    person: str
    location: str
    evidence: str

    @classmethod
    def from_models(
        cls, message: ParsedMessage, candidate: LocationEventCandidate
    ) -> CandidateEvidence:
        return cls(
            source_text=message.text,
            person=_normalized(candidate.person_mention),
            location=_normalized(candidate.location_mention),
            evidence=_normalized(candidate.evidence_text),
        )


class CandidateValidator:
    """Validate typed semantics and provenance without interpreting message language."""

    def validate(
        self, message: ParsedMessage, candidate: LocationEventCandidate
    ) -> ValidationResult:
        evidence = CandidateEvidence.from_models(message, candidate)

        rejection = _validate_required_fields(evidence)
        rejection = rejection or _validate_semantics(candidate)
        rejection = rejection or _validate_evidence_provenance(evidence)
        if rejection:
            return _rejected(candidate, rejection)

        normalized_candidate, rejection = _normalize_evidence_span(candidate, evidence)
        if rejection:
            return _rejected(candidate, rejection)

        return ValidationResult(accepted=True, candidate=normalized_candidate)


def _validate_required_fields(evidence: CandidateEvidence) -> RejectionReason | None:
    if not evidence.person:
        return RejectionReason.MISSING_PERSON
    if not evidence.location:
        return RejectionReason.MISSING_LOCATION
    if not evidence.evidence:
        return RejectionReason.MISSING_EVIDENCE
    return None


def _validate_semantics(candidate: LocationEventCandidate) -> RejectionReason | None:
    if candidate.person_reference is not MentionReference.EXPLICIT:
        return RejectionReason.UNSUPPORTED_PERSON_REFERENCE
    if candidate.location_reference is not MentionReference.EXPLICIT:
        return RejectionReason.UNSUPPORTED_LOCATION_REFERENCE
    if candidate.ambiguous or candidate.polarity is Polarity.UNKNOWN:
        return RejectionReason.AMBIGUOUS
    if candidate.relation is LocationRelation.UNKNOWN:
        return RejectionReason.UNKNOWN_RELATION
    if not _polarity_matches_certainty(candidate):
        return RejectionReason.CERTAINTY_CONFLICT
    return None


def _validate_evidence_provenance(evidence: CandidateEvidence) -> RejectionReason | None:
    if evidence.evidence not in evidence.source_text:
        return RejectionReason.EVIDENCE_MISMATCH
    if not _contains_literal(evidence.evidence, evidence.person):
        return RejectionReason.EVIDENCE_MISMATCH
    if not _contains_literal(evidence.evidence, evidence.location):
        return RejectionReason.EVIDENCE_MISMATCH
    return None


def _normalize_evidence_span(
    candidate: LocationEventCandidate, evidence: CandidateEvidence
) -> tuple[LocationEventCandidate, RejectionReason | None]:
    start = candidate.evidence_start
    end = candidate.evidence_end

    if (start is None) != (end is None):
        return candidate, RejectionReason.INVALID_EVIDENCE_SPAN
    if start is not None and end is not None and _span_matches(evidence, start, end):
        return candidate, None
    if evidence.source_text.count(evidence.evidence) != 1:
        return candidate, RejectionReason.INVALID_EVIDENCE_SPAN

    actual_start = evidence.source_text.index(evidence.evidence)
    normalized = candidate.model_copy(
        update={
            "evidence_start": actual_start,
            "evidence_end": actual_start + len(evidence.evidence),
        }
    )
    return normalized, None


def _polarity_matches_certainty(candidate: LocationEventCandidate) -> bool:
    negative_polarity = candidate.polarity is Polarity.NEGATIVE
    negative_certainty = candidate.certainty is Certainty.NEGATED
    return negative_polarity == negative_certainty


def _span_matches(evidence: CandidateEvidence, start: int, end: int) -> bool:
    return 0 <= start < end <= len(evidence.source_text) and (
        evidence.source_text[start:end] == evidence.evidence
    )


def _contains_literal(text: str, mention: str) -> bool:
    return mention.casefold() in text.casefold()


def _normalized(value: str | None) -> str:
    return value.strip() if value else ""


def _rejected(candidate: LocationEventCandidate, reason: RejectionReason) -> ValidationResult:
    return ValidationResult(accepted=False, candidate=candidate, reason=reason)
