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
    from location_extractor.resolution_evaluation import (
        ResolutionEvaluationReport,
        SemanticRankingDiagnostics,
    )

PROJECT_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

DEFAULT_DATASET = PROJECT_ROOT / "tests" / "fixtures" / "resolution_cases.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "evaluation-results" / "reranker-resolution-eval.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare embedding and reranked retrieval")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--embedding-model", type=str)
    parser.add_argument("--reranker-model", type=str)
    parser.add_argument("--embedding-top-k", type=int)
    parser.add_argument("--reranker-top-n", type=int)
    parser.add_argument("--runs", type=int, default=1)
    return parser.parse_args()


async def run(
    dataset_path: Path,
    *,
    embedding_model_override: str | None = None,
    reranker_model_override: str | None = None,
    embedding_top_k_override: int | None = None,
    reranker_top_n_override: int | None = None,
) -> tuple[
    ResolutionEvaluationReport,
    ResolutionEvaluationReport,
    SemanticRankingDiagnostics,
    SemanticRankingDiagnostics,
    dict[str, str | int],
]:
    from location_extractor.config import Settings
    from location_extractor.db import Base
    from location_extractor.embedding_retrieval import (
        HybridEmbeddingCandidateRetriever,
        OpenAICompatibleEmbedder,
        RerankingCandidateRetriever,
    )
    from location_extractor.reranker import OpenAICompatibleReranker
    from location_extractor.resolution import DeterministicResolutionPolicy
    from location_extractor.resolution_evaluation import (
        ResolutionPrediction,
        load_resolution_dataset,
        mention_for_case,
        score_resolution_predictions,
        seed_resolution_dataset,
        semantic_ranking_diagnostics,
    )
    from location_extractor.resolution_repository import SqlAlchemyEntityResolutionRepository

    settings = Settings()
    embedding_api_key = settings.embedding_api_key or settings.openai_api_key
    reranker_api_key = settings.reranker_api_key or embedding_api_key
    base_url = settings.reranker_base_url or settings.embedding_base_url or settings.openai_base_url
    if not embedding_api_key or not reranker_api_key or not base_url:
        raise SystemExit("embedding/reranker API key and base URL must be configured")
    embedding_model = embedding_model_override or settings.embedding_model
    reranker_model = reranker_model_override or settings.reranker_model
    embedding_top_k = embedding_top_k_override or settings.embedding_top_k
    reranker_top_n = reranker_top_n_override or settings.reranker_top_n

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyEntityResolutionRepository(sessionmaker(engine, expire_on_commit=False))
    dataset = load_resolution_dataset(dataset_path)
    seed_resolution_dataset(repository, dataset)
    embedder = OpenAICompatibleEmbedder(
        api_key=embedding_api_key,
        base_url=settings.embedding_base_url or settings.openai_base_url,
        allow_insecure_http=settings.allow_insecure_http,
        trust_env=settings.openai_trust_env,
        model=embedding_model,
        dimensions=settings.embedding_dimensions,
        timeout_seconds=settings.embedding_timeout_seconds,
        max_retries=settings.embedding_max_retries,
    )
    embedding_retriever = HybridEmbeddingCandidateRetriever(
        repository,
        embedder,
        top_k=embedding_top_k,
        corpus_limit=settings.embedding_corpus_limit,
    )
    reranker = OpenAICompatibleReranker(
        api_key=reranker_api_key,
        base_url=base_url,
        model=reranker_model,
        timeout_seconds=settings.reranker_timeout_seconds,
        max_retries=settings.reranker_max_retries,
        allow_insecure_http=settings.allow_insecure_http,
        trust_env=settings.openai_trust_env,
    )
    reranked_retriever = RerankingCandidateRetriever(
        embedding_retriever, reranker, top_n=reranker_top_n
    )
    policy = DeterministicResolutionPolicy()
    embedding_predictions: list[ResolutionPrediction] = []
    reranked_predictions: list[ResolutionPrediction] = []
    try:
        for case in dataset.cases:
            mention = mention_for_case(case)
            embedding_candidates = await embedding_retriever.retrieve(mention)
            reranked_candidates = await reranked_retriever.retrieve(mention)
            embedding_predictions.append(
                ResolutionPrediction(
                    candidates=embedding_candidates,
                    decision=policy.decide(mention, embedding_candidates),
                )
            )
            reranked_predictions.append(
                ResolutionPrediction(
                    candidates=reranked_candidates,
                    decision=policy.decide(mention, reranked_candidates),
                )
            )
    finally:
        await reranker.aclose()
    metadata: dict[str, str | int] = {
        "embedding_model": embedding_model,
        "reranker_model": reranker_model,
        "embedding_top_k": embedding_top_k,
        "reranker_top_n": reranker_top_n,
    }
    return (
        score_resolution_predictions(dataset, embedding_predictions),
        score_resolution_predictions(dataset, reranked_predictions),
        semantic_ranking_diagnostics(dataset, embedding_predictions, use_reranker_score=False),
        semantic_ranking_diagnostics(dataset, reranked_predictions, use_reranker_score=True),
        metadata,
    )


async def main() -> None:
    from location_extractor.embedding_retrieval import EmbeddingProviderError
    from location_extractor.reranker import RerankerProviderError

    arguments = parse_args()
    if arguments.runs < 1:
        raise SystemExit("--runs must be positive")
    stability_runs: list[dict[str, object]] = []
    try:
        for run_number in range(1, arguments.runs + 1):
            (
                embedding_report,
                reranked_report,
                embedding_diagnostics,
                reranker_diagnostics,
                metadata,
            ) = await run(
                arguments.dataset,
                embedding_model_override=arguments.embedding_model,
                reranker_model_override=arguments.reranker_model,
                embedding_top_k_override=arguments.embedding_top_k,
                reranker_top_n_override=arguments.reranker_top_n,
            )
            stability_runs.append(
                {
                    "run": run_number,
                    "embedding_top_1_accuracy": embedding_report.metrics.top_1_accuracy,
                    "reranker_top_1_accuracy": reranked_report.metrics.top_1_accuracy,
                    "reranker_minimum_correct_margin": (
                        reranker_diagnostics.minimum_correct_top_1_margin
                    ),
                    "reranker_maximum_unresolved_score": (
                        reranker_diagnostics.maximum_unresolved_top_score
                    ),
                }
            )
    except (EmbeddingProviderError, RerankerProviderError) as exc:
        raise SystemExit(str(exc)) from None
    payload = {
        "metadata": {
            "retriever": "exact-first-embedding-reranker-v1",
            **metadata,
            "run_count": arguments.runs,
            "dataset": str(arguments.dataset),
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "ranking_diagnostics": {
            "embedding_only": embedding_diagnostics.model_dump(mode="json"),
            "reranked": reranker_diagnostics.model_dump(mode="json"),
        },
        "stability_runs": stability_runs,
        "embedding_only": embedding_report.model_dump(mode="json"),
        "reranked": reranked_report.model_dump(mode="json"),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(f"Detailed report: {arguments.output}")


if __name__ == "__main__":
    asyncio.run(main())
