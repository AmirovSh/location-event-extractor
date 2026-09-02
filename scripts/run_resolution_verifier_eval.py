from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

DEFAULT_DATASET = PROJECT_ROOT / "tests" / "fixtures" / "resolution_cases.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "evaluation-results" / "resolution-verifier-eval.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate pairwise semantic entity verification")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--embedding-model", type=str)
    parser.add_argument("--verifier-model", type=str)
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--concurrency", type=int, default=2)
    return parser.parse_args()


async def run(arguments: argparse.Namespace) -> dict[str, object]:
    from location_extractor.config import Settings
    from location_extractor.config_loader import (
        load_resolution_adjudication_prompt,
        load_resolution_verification_prompt,
    )
    from location_extractor.db import Base
    from location_extractor.embedding_retrieval import (
        HybridEmbeddingCandidateRetriever,
        OpenAICompatibleEmbedder,
    )
    from location_extractor.resolution import (
        EntityMention,
        PairwiseVerification,
        ResolutionCandidate,
        ResolutionConfidence,
        ResolutionFactor,
        VerificationVerdict,
        VerifiedResolutionPolicy,
    )
    from location_extractor.resolution_evaluation import (
        ResolutionPrediction,
        load_resolution_dataset,
        mention_for_case,
        score_resolution_predictions,
        seed_resolution_dataset,
    )
    from location_extractor.resolution_repository import SqlAlchemyEntityResolutionRepository
    from location_extractor.semantic_verification import OpenAICompatiblePairwiseVerifier
    from location_extractor.semantic_verification_evaluation import (
        PairVerificationPrediction,
        score_pair_verifications,
    )

    if arguments.concurrency < 1:
        raise SystemExit("--concurrency must be positive")
    settings = Settings()
    api_key = settings.embedding_api_key or settings.openai_api_key
    if not api_key:
        raise SystemExit("embedding/verifier API key is not configured")
    embedding_model = arguments.embedding_model or settings.embedding_model
    verifier_model = arguments.verifier_model or settings.openai_model
    top_k = arguments.top_k or settings.embedding_top_k
    prompt_version, system_prompt = load_resolution_verification_prompt()
    adjudication_prompt_version, adjudication_system_prompt = load_resolution_adjudication_prompt()

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyEntityResolutionRepository(sessionmaker(engine, expire_on_commit=False))
    dataset = load_resolution_dataset(arguments.dataset)
    seed_resolution_dataset(repository, dataset)
    embedder = OpenAICompatibleEmbedder(
        api_key=api_key,
        base_url=settings.embedding_base_url or settings.openai_base_url,
        allow_insecure_http=settings.allow_insecure_http,
        trust_env=settings.openai_trust_env,
        model=embedding_model,
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
    verifier = OpenAICompatiblePairwiseVerifier(
        api_key=settings.openai_api_key or api_key,
        base_url=settings.openai_base_url,
        allow_insecure_http=settings.allow_insecure_http,
        trust_env=settings.openai_trust_env,
        api_mode=settings.openai_api_mode,
        max_output_tokens=settings.openai_max_output_tokens,
        enable_thinking=settings.openai_enable_thinking,
        temperature=settings.openai_temperature,
        model=verifier_model,
        timeout_seconds=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
        prompt_version=prompt_version,
        system_prompt=system_prompt,
        adjudication_prompt_version=adjudication_prompt_version,
        adjudication_system_prompt=adjudication_system_prompt,
    )
    semaphore = asyncio.Semaphore(arguments.concurrency)
    policy = VerifiedResolutionPolicy()
    resolution_predictions: list[ResolutionPrediction] = []
    pair_predictions: list[PairVerificationPrediction] = []
    case_details: list[dict[str, object]] = []

    async def verify_pair(
        mention: EntityMention, candidate: ResolutionCandidate
    ) -> PairwiseVerification:
        async with semaphore:
            return await verifier.verify(mention, candidate)

    for case in dataset.cases:
        mention = mention_for_case(case)
        candidates = await retriever.retrieve(mention)
        is_exact = bool(candidates and ResolutionFactor.EXACT_ALIAS in candidates[0].factors)
        verifications = (
            []
            if is_exact
            else list(
                await asyncio.gather(*(verify_pair(mention, candidate) for candidate in candidates))
            )
        )
        confirmed_count = sum(
            verification.verdict is VerificationVerdict.SAME_ENTITY
            and not verification.insufficient_context
            and verification.confidence in (ResolutionConfidence.HIGH, ResolutionConfidence.MEDIUM)
            for verification in verifications
        )
        candidate_set_verification = None
        if confirmed_count > 1:
            async with semaphore:
                candidate_set_verification = await verifier.verify_candidate_set(
                    mention, candidates
                )
        decision = policy.decide(mention, candidates, verifications, candidate_set_verification)
        resolution_predictions.append(
            ResolutionPrediction(candidates=candidates, decision=decision)
        )
        details: list[dict[str, object]] = []
        verified_candidates = [] if is_exact else candidates
        for candidate, verification in zip(verified_candidates, verifications, strict=True):
            expected = (
                VerificationVerdict.SAME_ENTITY
                if candidate.entity.id == case.expected_entity_id
                else VerificationVerdict.DIFFERENT_ENTITY
            )
            pair_predictions.append(
                PairVerificationPrediction(expected=expected, predicted=verification.verdict)
            )
            details.append(
                {
                    "candidate_name": candidate.entity.display_name,
                    "expected": expected.value,
                    "verification": verification.model_dump(mode="json"),
                }
            )
        case_details.append(
            {
                "name": case.name,
                "retrieval_mode": "exact" if is_exact else "semantic",
                "expected_outcome": case.expected_outcome.value,
                "predicted_outcome": decision.outcome.value,
                "candidate_verifications": details,
                "candidate_set_verification": (
                    candidate_set_verification.model_dump(mode="json")
                    if candidate_set_verification
                    else None
                ),
            }
        )

    resolution_report = score_resolution_predictions(dataset, resolution_predictions)
    return {
        "metadata": {
            "embedding_model": embedding_model,
            "verifier_model": verifier_model,
            "prompt_version": prompt_version,
            "adjudication_prompt_version": adjudication_prompt_version,
            "top_k": top_k,
            "concurrency": arguments.concurrency,
            "dataset": str(arguments.dataset),
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "pair_verification_metrics": score_pair_verifications(pair_predictions).model_dump(
            mode="json"
        ),
        "resolution_report": resolution_report.model_dump(mode="json"),
        "cases": case_details,
    }


async def main() -> None:
    from location_extractor.embedding_retrieval import EmbeddingProviderError
    from location_extractor.semantic_verification import VerificationProviderError

    arguments = parse_args()
    try:
        payload = await run(arguments)
    except (EmbeddingProviderError, VerificationProviderError) as exc:
        raise SystemExit(str(exc)) from None
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload["pair_verification_metrics"], indent=2))
    print(json.dumps(payload["resolution_report"], indent=2))
    print(f"Detailed report: {arguments.output}")


if __name__ == "__main__":
    asyncio.run(main())
