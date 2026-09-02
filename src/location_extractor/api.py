from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from location_extractor.application import (
    AlwaysPassDetector,
    ExtractionProviderError,
    LocationExtractionService,
)
from location_extractor.config import Settings, get_settings
from location_extractor.config_loader import (
    load_extraction_prompt,
    load_resolution_adjudication_prompt,
    load_resolution_verification_prompt,
)
from location_extractor.db import SqlAlchemyLocationEventRepository, create_session_factory
from location_extractor.domain import ParsedMessage, ProcessResult
from location_extractor.embedding_retrieval import (
    HybridEmbeddingCandidateRetriever,
    OpenAICompatibleEmbedder,
)
from location_extractor.fakes import FakeExtractor
from location_extractor.openai_adapter import OpenAIResponsesExtractor
from location_extractor.ports import LocationEventExtractor, MessageProcessor
from location_extractor.resolution_repository import SqlAlchemyEntityResolutionRepository
from location_extractor.resolution_workflow import (
    PersistedEventResolutionWorkflow,
    ResolvedLocationExtractionService,
)
from location_extractor.semantic_verification import OpenAICompatiblePairwiseVerifier
from location_extractor.validation import CandidateValidator


class JsonFormatter(logging.Formatter):
    _fields = (
        "message_id",
        "conversation_id",
        "text_length",
        "text_hash",
        "extractor_version",
        "relevant",
        "candidate_count",
        "accepted_count",
        "status",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {"level": record.levelname, "event": record.getMessage()}
        payload.update(
            {field: getattr(record, field) for field in self._fields if hasattr(record, field)}
        )
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())


def build_service(settings: Settings) -> MessageProcessor:
    sessions = create_session_factory(settings.database_url)
    repository = SqlAlchemyLocationEventRepository(sessions)
    extractor: LocationEventExtractor
    if settings.extractor_backend == "fake":
        extractor = FakeExtractor()
    elif settings.extractor_backend == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("LOCATION_OPENAI_API_KEY is required for the openai backend")
        prompt_file_version, system_prompt = load_extraction_prompt()
        if prompt_file_version != settings.prompt_version:
            raise RuntimeError("configured prompt version does not match prompts.toml")
        extractor = OpenAIResponsesExtractor(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            timeout_seconds=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
            prompt_version=settings.prompt_version,
            system_prompt=system_prompt,
            base_url=settings.openai_base_url,
            allow_insecure_http=settings.allow_insecure_http,
            trust_env=settings.openai_trust_env,
            api_mode=settings.openai_api_mode,
            max_output_tokens=settings.openai_max_output_tokens,
            enable_thinking=settings.openai_enable_thinking,
            temperature=settings.openai_temperature,
        )
    else:
        raise RuntimeError(f"unsupported extractor backend: {settings.extractor_backend}")
    extraction_service = LocationExtractionService(
        AlwaysPassDetector(),
        extractor,
        CandidateValidator(),
        repository,
        extractor_version=settings.extractor_version,
        schema_version=settings.schema_version,
    )
    if not settings.resolution_enabled:
        return extraction_service
    embedding_api_key = settings.embedding_api_key or settings.openai_api_key
    if not embedding_api_key:
        raise RuntimeError("embedding API key is required when resolution is enabled")
    verification_version, verification_prompt = load_resolution_verification_prompt()
    adjudication_version, adjudication_prompt = load_resolution_adjudication_prompt()
    resolution_repository = SqlAlchemyEntityResolutionRepository(sessions)
    embedder = OpenAICompatibleEmbedder(
        api_key=embedding_api_key,
        base_url=settings.embedding_base_url or settings.openai_base_url,
        allow_insecure_http=settings.allow_insecure_http,
        trust_env=settings.openai_trust_env,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        timeout_seconds=settings.embedding_timeout_seconds,
        max_retries=settings.embedding_max_retries,
    )
    retriever = HybridEmbeddingCandidateRetriever(
        resolution_repository,
        embedder,
        top_k=settings.embedding_top_k,
        corpus_limit=settings.embedding_corpus_limit,
    )
    verifier = OpenAICompatiblePairwiseVerifier(
        api_key=settings.openai_api_key or embedding_api_key,
        base_url=settings.openai_base_url,
        allow_insecure_http=settings.allow_insecure_http,
        trust_env=settings.openai_trust_env,
        api_mode=settings.openai_api_mode,
        max_output_tokens=settings.openai_max_output_tokens,
        enable_thinking=settings.openai_enable_thinking,
        temperature=settings.openai_temperature,
        model=settings.resolution_verifier_model,
        timeout_seconds=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
        prompt_version=verification_version,
        system_prompt=verification_prompt,
        adjudication_prompt_version=adjudication_version,
        adjudication_system_prompt=adjudication_prompt,
    )
    return ResolvedLocationExtractionService(
        extraction_service,
        PersistedEventResolutionWorkflow(
            resolution_repository,
            retriever,
            verifier,
            verifier,
            verifier_concurrency=settings.resolution_verifier_concurrency,
        ),
    )


def create_app(
    service_factory: Callable[[], MessageProcessor] | None = None,
) -> FastAPI:
    app = FastAPI(title="Location Event Extractor", version="0.1.0")

    def service_dependency() -> MessageProcessor:
        if service_factory is not None:
            return service_factory()
        return build_service(get_settings())

    @app.exception_handler(ExtractionProviderError)
    async def provider_error_handler(
        request: Request, exc: ExtractionProviderError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": "extraction provider unavailable", "category": "provider_error"},
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/location-events/extract", response_model=ProcessResult)
    async def extract(
        message: ParsedMessage, service: MessageProcessor = Depends(service_dependency)
    ) -> ProcessResult:
        try:
            return await service.process(message)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app


app = create_app()
