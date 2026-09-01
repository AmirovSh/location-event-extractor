from __future__ import annotations

import hashlib
import logging
import time

from location_extractor.domain import CandidateOutcome, ParsedMessage, ProcessResult, RunStatus
from location_extractor.ports import (
    LocationCandidateDetector,
    LocationEventExtractor,
    LocationEventRepository,
)
from location_extractor.validation import CandidateValidator

logger = logging.getLogger(__name__)


class AlwaysPassDetector:
    async def is_relevant(self, message: ParsedMessage) -> bool:
        return True


class ExtractionProviderError(RuntimeError):
    """Bounded public error for failures at the external model boundary."""


class LocationExtractionService:
    def __init__(
        self,
        detector: LocationCandidateDetector,
        extractor: LocationEventExtractor,
        validator: CandidateValidator,
        repository: LocationEventRepository,
        *,
        extractor_version: str,
        schema_version: str,
    ) -> None:
        self.detector = detector
        self.extractor = extractor
        self.validator = validator
        self.repository = repository
        self.extractor_version = extractor_version
        self.schema_version = schema_version

    async def process(self, message: ParsedMessage) -> ProcessResult:
        started = time.monotonic()
        log_context = {
            "message_id": message.message_id,
            "conversation_id": message.conversation_id,
            "text_length": len(message.text),
            "text_hash": hashlib.sha256(message.text.encode()).hexdigest(),
            "extractor_version": self.extractor_version,
        }
        logger.info("message_received", extra=log_context)
        existing = self.repository.get_result(message, self.extractor_version, self.schema_version)
        if existing is not None:
            logger.info("idempotent_replay", extra=log_context)
            return existing.model_copy(update={"replayed": True})

        relevant = await self.detector.is_relevant(message)
        logger.info("detector_decision", extra={**log_context, "relevant": relevant})
        if not relevant:
            return self._save(message, RunStatus.NO_EVENT, [], started)

        extraction = await self.extractor.extract(message)
        logger.info(
            "extractor_completed", extra={**log_context, "candidate_count": len(extraction.events)}
        )
        outcomes: list[CandidateOutcome] = []
        for candidate in extraction.events:
            validation = self.validator.validate(message, candidate)
            outcomes.append(
                CandidateOutcome(
                    candidate=validation.candidate,
                    persisted=validation.accepted,
                    rejection_reason=validation.reason,
                )
            )

        status = _status_for(outcomes)
        logger.info(
            "validation_completed",
            extra={
                **log_context,
                "status": status,
                "accepted_count": sum(outcome.persisted for outcome in outcomes),
            },
        )
        return self._save(message, status, outcomes, started)

    def _save(
        self,
        message: ParsedMessage,
        status: RunStatus,
        outcomes: list[CandidateOutcome],
        started: float,
    ) -> ProcessResult:
        result = self.repository.save_result(
            message,
            self.extractor_version,
            self.schema_version,
            self.extractor.provider,
            self.extractor.model,
            status,
            outcomes,
            round((time.monotonic() - started) * 1000),
        )
        logger.info(
            "persistence_completed",
            extra={"message_id": message.message_id, "status": result.status},
        )
        return result


def _status_for(outcomes: list[CandidateOutcome]) -> RunStatus:
    if not outcomes:
        return RunStatus.NO_EVENT
    accepted = sum(outcome.persisted for outcome in outcomes)
    if accepted == len(outcomes):
        return RunStatus.PERSISTED
    if accepted:
        return RunStatus.PARTIAL
    return RunStatus.REJECTED
