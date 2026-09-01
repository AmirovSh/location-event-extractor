from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from location_extractor.domain import (
    CandidateOutcome,
    ExtractionResult,
    ParsedMessage,
    ProcessResult,
    RunStatus,
)


class FakeExtractor:
    provider = "fake"
    model = "fixture"

    def __init__(self, result: ExtractionResult | None = None) -> None:
        self.result = result or ExtractionResult()
        self.calls: list[ParsedMessage] = []

    async def extract(self, message: ParsedMessage) -> ExtractionResult:
        self.calls.append(message)
        return self.result.model_copy(deep=True)


@dataclass
class InMemoryRepository:
    results: dict[tuple[str, str, str, str], ProcessResult] = field(default_factory=dict)
    message_hashes: dict[tuple[str, str], str] = field(default_factory=dict)

    def get_result(
        self, message: ParsedMessage, extractor_version: str, schema_version: str
    ) -> ProcessResult | None:
        self._verify_message_identity(message)
        result = self.results.get(self._key(message, extractor_version, schema_version))
        return deepcopy(result)

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
        self._verify_message_identity(message)
        self.message_hashes[self._message_key(message)] = self._text_hash(message.text)
        key = self._key(message, extractor_version, schema_version)
        existing = self.results.get(key)
        if existing:
            return existing.model_copy(update={"replayed": True})
        saved = [
            outcome.model_copy(update={"event_id": uuid4()}) if outcome.persisted else outcome
            for outcome in outcomes
        ]
        result = ProcessResult(message_id=message.message_id, status=status, outcomes=saved)
        self.results[key] = deepcopy(result)
        return result

    def _verify_message_identity(self, message: ParsedMessage) -> None:
        existing_hash = self.message_hashes.get(self._message_key(message))
        if existing_hash is not None and existing_hash != self._text_hash(message.text):
            raise ValueError("message identity reused with different text")

    @staticmethod
    def _message_key(message: ParsedMessage) -> tuple[str, str]:
        return message.conversation_id, message.message_id

    @staticmethod
    def _text_hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    @staticmethod
    def _key(
        message: ParsedMessage, extractor_version: str, schema_version: str
    ) -> tuple[str, str, str, str]:
        return (
            message.conversation_id,
            message.message_id,
            extractor_version,
            schema_version,
        )


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidGenerator:
    def new(self) -> UUID:
        return uuid4()
