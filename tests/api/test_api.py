from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from location_extractor.api import create_app
from location_extractor.application import (
    AlwaysPassDetector,
    ExtractionProviderError,
    LocationExtractionService,
)
from location_extractor.domain import ExtractionResult, LocationEventCandidate, ParsedMessage
from location_extractor.fakes import FakeExtractor, InMemoryRepository
from location_extractor.validation import CandidateValidator


def message_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "conversation_id": "conv-42",
        "message_id": "msg-1001",
        "author_id": "user-5",
        "sent_at": "2026-08-31T10:15:00+05:00",
        "text": "John is in London now",
    }
    payload.update(updates)
    return payload


def candidate(
    person: str = "John",
    location: str = "London",
    evidence: str = "John is in London now",
    **updates: Any,
) -> LocationEventCandidate:
    values: dict[str, Any] = {
        "person_mention": person,
        "location_mention": location,
        "relation": "AT",
        "certainty": "ASSERTED",
        "evidence_text": evidence,
    }
    values.update(updates)
    return LocationEventCandidate(**values)


def build_client(
    extraction: ExtractionResult | None = None,
    *,
    extractor: FakeExtractor | ProviderFailureExtractor | None = None,
    repository: InMemoryRepository | None = None,
) -> tuple[TestClient, FakeExtractor | ProviderFailureExtractor]:
    selected_extractor = extractor or FakeExtractor(extraction)
    service = LocationExtractionService(
        AlwaysPassDetector(),
        selected_extractor,
        CandidateValidator(),
        repository or InMemoryRepository(),
        extractor_version="test",
        schema_version="1.0",
    )
    return TestClient(create_app(lambda: service)), selected_extractor


class ProviderFailureExtractor:
    provider = "fake"
    model = "failure"

    async def extract(self, message: ParsedMessage) -> ExtractionResult:
        raise ExtractionProviderError("private provider details")


def test_persisted_event_response() -> None:
    client, _ = build_client(ExtractionResult(events=[candidate()]))
    response = client.post("/v1/location-events/extract", json=message_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PERSISTED"
    assert body["outcomes"][0]["candidate"]["person_mention"] == "John"
    assert body["outcomes"][0]["event_id"]


def test_no_event_response() -> None:
    client, _ = build_client(ExtractionResult())
    response = client.post("/v1/location-events/extract", json=message_payload())
    assert response.status_code == 200
    assert response.json() == {
        "message_id": "msg-1001",
        "status": "NO_EVENT",
        "outcomes": [],
        "replayed": False,
    }


def test_rejected_response() -> None:
    unresolved = candidate(person="He", person_reference="REFERENCE", evidence="He is in London")
    client, _ = build_client(ExtractionResult(events=[unresolved]))
    response = client.post(
        "/v1/location-events/extract",
        json=message_payload(text="He is in London"),
    )
    assert response.status_code == 200
    outcome = response.json()["outcomes"][0]
    assert response.json()["status"] == "REJECTED"
    assert outcome["persisted"] is False
    assert outcome["event_id"] is None
    assert outcome["rejection_reason"] == "UNSUPPORTED_PERSON_REFERENCE"


def test_partial_response() -> None:
    unresolved = candidate(
        person="Mary",
        location="there",
        evidence="Mary is there",
        location_reference="REFERENCE",
    )
    extraction = ExtractionResult(events=[candidate(), unresolved])
    client, _ = build_client(extraction)
    response = client.post(
        "/v1/location-events/extract",
        json=message_payload(text="John is in London now, and Mary is there"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PARTIAL"
    assert [outcome["persisted"] for outcome in body["outcomes"]] == [True, False]
    assert body["outcomes"][1]["rejection_reason"] == "UNSUPPORTED_LOCATION_REFERENCE"


def test_idempotent_replay_does_not_call_extractor_twice() -> None:
    client, extractor = build_client(ExtractionResult(events=[candidate()]))
    first = client.post("/v1/location-events/extract", json=message_payload())
    replay = client.post("/v1/location-events/extract", json=message_payload())
    assert first.status_code == replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["outcomes"][0]["event_id"] == first.json()["outcomes"][0]["event_id"]
    assert isinstance(extractor, FakeExtractor)
    assert len(extractor.calls) == 1


def test_reused_message_identity_with_different_text_is_409() -> None:
    client, extractor = build_client(ExtractionResult(events=[candidate()]))
    assert client.post("/v1/location-events/extract", json=message_payload()).status_code == 200
    conflict = client.post(
        "/v1/location-events/extract",
        json=message_payload(text="John is in Paris now"),
    )
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "message identity reused with different text"}
    assert isinstance(extractor, FakeExtractor)
    assert len(extractor.calls) == 1


def test_provider_failure_is_bounded_503() -> None:
    client, _ = build_client(extractor=ProviderFailureExtractor())
    response = client.post("/v1/location-events/extract", json=message_payload())
    assert response.status_code == 503
    assert response.json() == {
        "detail": "extraction provider unavailable",
        "category": "provider_error",
    }
    assert "private provider details" not in response.text


def test_malformed_input_is_422() -> None:
    client, _ = build_client()
    response = client.post("/v1/location-events/extract", json={"text": "John is in London"})
    assert response.status_code == 422
