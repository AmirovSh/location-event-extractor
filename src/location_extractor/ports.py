from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from location_extractor.domain import (
    CandidateOutcome,
    ExtractionResult,
    ParsedMessage,
    ProcessResult,
    RunStatus,
)


class LocationCandidateDetector(Protocol):
    async def is_relevant(self, message: ParsedMessage) -> bool: ...


class LocationEventExtractor(Protocol):
    @property
    def provider(self) -> str | None: ...

    @property
    def model(self) -> str | None: ...

    async def extract(self, message: ParsedMessage) -> ExtractionResult: ...


class LocationEventRepository(Protocol):
    def get_result(
        self, message: ParsedMessage, extractor_version: str, schema_version: str
    ) -> ProcessResult | None: ...

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
    ) -> ProcessResult: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new(self) -> UUID: ...
