from __future__ import annotations

from datetime import datetime

import pytest

from location_extractor.domain import (
    Certainty,
    LocationEventCandidate,
    LocationRelation,
    ParsedMessage,
    RejectionReason,
)
from location_extractor.validation import CandidateValidator


def message(text: str) -> ParsedMessage:
    return ParsedMessage(
        conversation_id="conv",
        message_id="msg",
        sent_at=datetime.fromisoformat("2026-08-31T10:15:00+05:00"),
        text=text,
    )


@pytest.mark.parametrize(
    ("text", "candidate", "accepted", "reason"),
    [
        (
            "Иван в Алматы.",
            {
                "person_mention": "Иван",
                "location_mention": "Алматы",
                "relation": "AT",
                "certainty": "ASSERTED",
                "evidence_text": "Иван в Алматы",
            },
            True,
            None,
        ),
        (
            "Петр приехал в Астану.",
            {
                "person_mention": "Петр",
                "location_mention": "Астану",
                "relation": "ARRIVED",
                "certainty": "ASSERTED",
                "evidence_text": "Петр приехал в Астану",
            },
            True,
            None,
        ),
        (
            "Сергей вышел из офиса.",
            {
                "person_mention": "Сергей",
                "location_mention": "офиса",
                "relation": "LEFT",
                "certainty": "ASSERTED",
                "evidence_text": "Сергей вышел из офиса",
            },
            True,
            None,
        ),
        (
            "Иван не в Алматы.",
            {
                "person_mention": "Иван",
                "location_mention": "Алматы",
                "relation": "AT",
                "certainty": "NEGATED",
                "evidence_text": "Иван не в Алматы",
            },
            True,
            None,
        ),
        (
            "Наверное, Иван в Алматы.",
            {
                "person_mention": "Иван",
                "location_mention": "Алматы",
                "relation": "AT",
                "certainty": "PROBABLE",
                "evidence_text": "Наверное, Иван в Алматы",
            },
            True,
            None,
        ),
        (
            "Иван может быть в Алматы.",
            {
                "person_mention": "Иван",
                "location_mention": "Алматы",
                "relation": "AT",
                "certainty": "POSSIBLE",
                "evidence_text": "Иван может быть в Алматы",
            },
            True,
            None,
        ),
        (
            "Иван завтра поедет в Алматы.",
            {
                "person_mention": "Иван",
                "location_mention": "Алматы",
                "relation": "TO",
                "certainty": "PLANNED",
                "temporal_raw": "завтра",
                "evidence_text": "Иван завтра поедет в Алматы",
            },
            True,
            None,
        ),
        (
            "He is in Almaty.",
            {
                "person_mention": "He",
                "person_reference": "REFERENCE",
                "location_mention": "Almaty",
                "relation": "AT",
                "evidence_text": "He is in Almaty",
            },
            False,
            RejectionReason.UNSUPPORTED_PERSON_REFERENCE,
        ),
        (
            "John is there.",
            {
                "person_mention": "John",
                "location_mention": "there",
                "location_reference": "REFERENCE",
                "relation": "AT",
                "evidence_text": "John is there",
            },
            False,
            RejectionReason.UNSUPPORTED_LOCATION_REFERENCE,
        ),
        (
            "Иван в Алматы.",
            {
                "person_mention": "Иван",
                "location_mention": "Астана",
                "relation": "AT",
                "evidence_text": "Иван в Алматы",
            },
            False,
            RejectionReason.EVIDENCE_MISMATCH,
        ),
        (
            "Иван в Алматы.",
            {
                "person_mention": "Иван",
                "location_mention": "Алматы",
                "relation": "UNKNOWN",
                "evidence_text": "Иван в Алматы",
            },
            False,
            RejectionReason.UNKNOWN_RELATION,
        ),
    ],
)
def test_persistability_table(
    text: str, candidate: dict[str, object], accepted: bool, reason: RejectionReason | None
) -> None:
    result = CandidateValidator().validate(message(text), LocationEventCandidate(**candidate))
    assert result.accepted is accepted
    assert result.reason == reason


def test_unicode_offsets_are_python_character_offsets() -> None:
    text = "📍 Иван в Алматы."
    evidence = "Иван в Алматы"
    start = text.index(evidence)
    candidate = LocationEventCandidate(
        person_mention="Иван",
        location_mention="Алматы",
        relation=LocationRelation.AT,
        certainty=Certainty.ASSERTED,
        evidence_text=evidence,
        evidence_start=start,
        evidence_end=start + len(evidence),
    )
    assert CandidateValidator().validate(message(text), candidate).accepted


def test_unique_evidence_repairs_provider_offset() -> None:
    text = "Иван сейчас в Алматы."
    candidate = LocationEventCandidate(
        person_mention="Иван",
        location_mention="Алматы",
        relation=LocationRelation.AT,
        certainty=Certainty.ASSERTED,
        evidence_text=text,
        evidence_start=0,
        evidence_end=len(text) + 1,
    )
    result = CandidateValidator().validate(message(text), candidate)
    assert result.accepted
    assert result.candidate.evidence_start == 0
    assert result.candidate.evidence_end == len(text)


def test_explicit_negation_cannot_persist_as_asserted() -> None:
    text = "John is not in London."
    candidate = LocationEventCandidate(
        person_mention="John",
        location_mention="London",
        relation=LocationRelation.AT,
        certainty=Certainty.ASSERTED,
        polarity="NEGATIVE",
        evidence_text="John is not in London",
    )
    result = CandidateValidator().validate(message(text), candidate)
    assert not result.accepted
    assert result.reason is RejectionReason.CERTAINTY_CONFLICT
