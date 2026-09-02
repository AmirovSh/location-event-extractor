from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

if TYPE_CHECKING:
    from location_extractor.resolution_evaluation import ResolutionEvaluationReport

PROJECT_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

DEFAULT_DATASET = PROJECT_ROOT / "tests" / "fixtures" / "resolution_cases.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "evaluation-results" / "embedding-resolution-eval.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run opt-in embedding resolution evaluation")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", type=str)
    parser.add_argument("--top-k", type=int)
    return parser.parse_args()


async def run(
    dataset_path: Path,
    *,
    model_override: str | None = None,
    top_k_override: int | None = None,
) -> tuple[ResolutionEvaluationReport, str, int]:
    from location_extractor.config import Settings
    from location_extractor.db import Base
    from location_extractor.embedding_retrieval import (
        HybridEmbeddingCandidateRetriever,
        OpenAICompatibleEmbedder,
    )
    from location_extractor.resolution import DeterministicResolutionPolicy
    from location_extractor.resolution_evaluation import (
        ResolutionPrediction,
        load_resolution_dataset,
        mention_for_case,
        score_resolution_predictions,
        seed_resolution_dataset,
    )
    from location_extractor.resolution_repository import (
        SqlAlchemyEntityResolutionRepository,
    )

    settings = Settings()
    api_key = settings.embedding_api_key or settings.openai_api_key
    if not api_key:
        raise SystemExit("embedding API key is not configured")
    model = model_override or settings.embedding_model
    top_k = top_k_override or settings.embedding_top_k
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyEntityResolutionRepository(sessionmaker(engine, expire_on_commit=False))
    dataset = load_resolution_dataset(dataset_path)
    seed_resolution_dataset(repository, dataset)
    embedder = OpenAICompatibleEmbedder(
        api_key=api_key,
        base_url=settings.embedding_base_url or settings.openai_base_url,
        allow_insecure_http=settings.allow_insecure_http,
        trust_env=settings.openai_trust_env,
        model=model,
        dimensions=settings.embedding_dimensions,
        timeout_seconds=settings.embedding_timeout_seconds,
        max_retries=settings.embedding_max_retries,
    )
    retriever = HybridEmbeddingCandidateRetriever(
        repository,
        embedder,
        top_k=top_k,
        corpus_limit=settings.embedding_corpus_limit,
    )
    policy = DeterministicResolutionPolicy()
    predictions: list[ResolutionPrediction] = []
    for case in dataset.cases:
        mention = mention_for_case(case)
        candidates = await retriever.retrieve(mention)
        predictions.append(
            ResolutionPrediction(
                candidates=candidates,
                decision=policy.decide(mention, candidates),
            )
        )
    return score_resolution_predictions(dataset, predictions), model, top_k


async def main() -> None:
    from location_extractor.embedding_retrieval import EmbeddingProviderError

    arguments = parse_args()
    try:
        report, model, top_k = await run(
            arguments.dataset,
            model_override=arguments.model,
            top_k_override=arguments.top_k,
        )
    except EmbeddingProviderError as exc:
        raise SystemExit(str(exc)) from None
    payload = {
        "metadata": {
            "retriever": "exact-first-embedding-v1",
            "model": model,
            "top_k": top_k,
            "dataset": str(arguments.dataset),
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "report": report.model_dump(mode="json"),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"Detailed report: {arguments.output}")


if __name__ == "__main__":
    asyncio.run(main())
