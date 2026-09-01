from __future__ import annotations

from fastapi.testclient import TestClient

from location_extractor.api import create_app
from location_extractor.application import AlwaysPassDetector, LocationExtractionService
from location_extractor.domain import ExtractionResult, LocationEventCandidate
from location_extractor.fakes import FakeExtractor, InMemoryRepository
from location_extractor.validation import CandidateValidator


def test_extract_endpoint() -> None:
    service = LocationExtractionService(
        AlwaysPassDetector(),
        FakeExtractor(
            ExtractionResult(
                events=[
                    LocationEventCandidate(
                        person_mention="Иван",
                        location_mention="Алматы",
                        relation="AT",
                        certainty="ASSERTED",
                        evidence_text="Иван сейчас в Алматы",
                        evidence_start=0,
                        evidence_end=20,
                    )
                ]
            )
        ),
        CandidateValidator(),
        InMemoryRepository(),
        extractor_version="test",
        schema_version="1.0",
    )
    client = TestClient(create_app(lambda: service))
    response = client.post(
        "/v1/location-events/extract",
        json={
            "conversation_id": "conv-42",
            "message_id": "msg-1001",
            "author_id": "user-5",
            "sent_at": "2026-08-31T10:15:00+05:00",
            "text": "Иван сейчас в Алматы",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PERSISTED"
    assert body["outcomes"][0]["candidate"]["person_mention"] == "Иван"
    assert body["outcomes"][0]["event_id"]


def test_malformed_input_is_422() -> None:
    service = LocationExtractionService(
        AlwaysPassDetector(),
        FakeExtractor(),
        CandidateValidator(),
        InMemoryRepository(),
        extractor_version="test",
        schema_version="1.0",
    )
    client = TestClient(create_app(lambda: service))
    response = client.post("/v1/location-events/extract", json={"text": "Иван в Алматы"})
    assert response.status_code == 422
