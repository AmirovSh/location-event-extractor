from __future__ import annotations

from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, Field

from location_extractor.ports import EntityResolutionPolicy, EntityResolutionRepository
from location_extractor.resolution import (
    AliasSource,
    CanonicalEntity,
    EntityAlias,
    EntityMention,
    EntityType,
    ResolutionCandidate,
    ResolutionDecision,
    ResolutionOutcome,
    ResolutionScope,
)


class ResolutionAliasFixture(BaseModel):
    alias: str
    scope: ResolutionScope
    source: AliasSource = AliasSource.SEED


class ResolutionEntityFixture(BaseModel):
    id: UUID
    tenant_id: str
    entity_type: EntityType
    display_name: str
    aliases: list[ResolutionAliasFixture]


class ResolutionCaseFixture(BaseModel):
    name: str
    mention: str
    entity_type: EntityType
    scope: ResolutionScope
    context: str | None = None
    expected_outcome: ResolutionOutcome
    expected_candidate_ids: list[UUID] = Field(default_factory=list)
    expected_entity_id: UUID | None = None


class ResolutionDataset(BaseModel):
    entities: list[ResolutionEntityFixture]
    cases: list[ResolutionCaseFixture]


class ResolutionEvaluationMetrics(BaseModel):
    candidate_recall_at_1: float
    candidate_recall_at_3: float
    candidate_set_recall: float
    top_1_accuracy: float
    outcome_accuracy: float
    resolved_precision: float
    automatic_resolution_coverage: float
    ambiguity_accuracy: float
    unresolved_accuracy: float


class ResolutionCaseResult(BaseModel):
    name: str
    expected_outcome: ResolutionOutcome
    predicted_outcome: ResolutionOutcome
    expected_entity_id: UUID | None
    predicted_entity_id: UUID | None
    expected_candidate_ids: list[UUID]
    predicted_candidate_ids: list[UUID]


class ResolutionEvaluationReport(BaseModel):
    case_count: int
    resolved_case_count: int
    tenant_leakage_count: int
    entity_type_leakage_count: int
    metrics: ResolutionEvaluationMetrics
    cases: list[ResolutionCaseResult]


class SemanticRankingDiagnostics(BaseModel):
    scored_resolved_case_count: int
    correct_top_1_count: int
    average_correct_top_1_margin: float | None
    minimum_correct_top_1_margin: float | None
    scored_unresolved_case_count: int
    average_unresolved_top_score: float | None
    maximum_unresolved_top_score: float | None


class ResolutionPrediction(BaseModel):
    candidates: list[ResolutionCandidate]
    decision: ResolutionDecision


def load_resolution_dataset(path: Path) -> ResolutionDataset:
    return ResolutionDataset.model_validate_json(path.read_text(encoding="utf-8"))


def seed_resolution_dataset(
    repository: EntityResolutionRepository, dataset: ResolutionDataset
) -> None:
    for fixture in dataset.entities:
        entity = CanonicalEntity(
            id=fixture.id,
            tenant_id=fixture.tenant_id,
            entity_type=fixture.entity_type,
            display_name=fixture.display_name,
        )
        repository.save_entity(
            entity,
            [
                EntityAlias(
                    canonical_entity_id=entity.id,
                    alias=alias.alias,
                    scope=alias.scope,
                    source=alias.source,
                )
                for alias in fixture.aliases
            ],
        )


def evaluate_resolution_dataset(
    repository: EntityResolutionRepository,
    policy: EntityResolutionPolicy,
    dataset: ResolutionDataset,
) -> ResolutionEvaluationReport:
    predictions: list[ResolutionPrediction] = []
    for case in dataset.cases:
        mention = mention_for_case(case)
        candidates = repository.find_candidates(mention)
        predictions.append(
            ResolutionPrediction(
                candidates=candidates,
                decision=policy.decide(mention, candidates),
            )
        )
    return score_resolution_predictions(dataset, predictions)


def mention_for_case(case: ResolutionCaseFixture) -> EntityMention:
    return EntityMention(
        entity_type=case.entity_type,
        text=case.mention,
        scope=case.scope,
        context=case.context,
    )


def score_resolution_predictions(
    dataset: ResolutionDataset, predictions: list[ResolutionPrediction]
) -> ResolutionEvaluationReport:
    if len(dataset.cases) != len(predictions):
        raise ValueError("resolution cases and predictions must have the same length")
    results: list[ResolutionCaseResult] = []
    tenant_leakage_count = entity_type_leakage_count = 0
    target_at_1 = target_at_3 = correct_top_1 = 0
    expected_candidate_count = retrieved_expected_candidate_count = 0
    correct_outcome = correct_resolution = predicted_resolution = 0
    correct_ambiguity = expected_ambiguity = 0
    correct_unresolved = expected_unresolved = 0

    for case, prediction in zip(dataset.cases, predictions, strict=True):
        candidates = prediction.candidates
        decision = prediction.decision
        candidate_ids = [candidate.entity.id for candidate in candidates]
        tenant_leakage_count += sum(
            candidate.entity.tenant_id != case.scope.tenant_id for candidate in candidates
        )
        entity_type_leakage_count += sum(
            candidate.entity.entity_type is not case.entity_type for candidate in candidates
        )
        expected_ids = set(case.expected_candidate_ids)
        expected_candidate_count += len(expected_ids)
        retrieved_expected_candidate_count += len(expected_ids.intersection(candidate_ids))

        if case.expected_entity_id is not None:
            target_at_1 += int(case.expected_entity_id in candidate_ids[:1])
            target_at_3 += int(case.expected_entity_id in candidate_ids[:3])
            correct_top_1 += int(
                bool(candidate_ids) and candidate_ids[0] == case.expected_entity_id
            )
        correct_outcome += int(decision.outcome is case.expected_outcome)
        if decision.outcome is ResolutionOutcome.RESOLVED:
            predicted_resolution += 1
            correct_resolution += int(
                case.expected_outcome is ResolutionOutcome.RESOLVED
                and decision.canonical_entity_id == case.expected_entity_id
            )
        if case.expected_outcome is ResolutionOutcome.AMBIGUOUS:
            expected_ambiguity += 1
            correct_ambiguity += int(decision.outcome is ResolutionOutcome.AMBIGUOUS)
        if case.expected_outcome is ResolutionOutcome.UNRESOLVED:
            expected_unresolved += 1
            correct_unresolved += int(decision.outcome is ResolutionOutcome.UNRESOLVED)

        results.append(
            ResolutionCaseResult(
                name=case.name,
                expected_outcome=case.expected_outcome,
                predicted_outcome=decision.outcome,
                expected_entity_id=case.expected_entity_id,
                predicted_entity_id=decision.canonical_entity_id,
                expected_candidate_ids=case.expected_candidate_ids,
                predicted_candidate_ids=candidate_ids,
            )
        )

    resolved_cases = sum(case.expected_entity_id is not None for case in dataset.cases)
    return ResolutionEvaluationReport(
        case_count=len(dataset.cases),
        resolved_case_count=resolved_cases,
        tenant_leakage_count=tenant_leakage_count,
        entity_type_leakage_count=entity_type_leakage_count,
        metrics=ResolutionEvaluationMetrics(
            candidate_recall_at_1=_ratio(target_at_1, resolved_cases),
            candidate_recall_at_3=_ratio(target_at_3, resolved_cases),
            candidate_set_recall=_ratio(
                retrieved_expected_candidate_count, expected_candidate_count
            ),
            top_1_accuracy=_ratio(correct_top_1, resolved_cases),
            outcome_accuracy=_ratio(correct_outcome, len(dataset.cases)),
            resolved_precision=_ratio(correct_resolution, predicted_resolution),
            automatic_resolution_coverage=_ratio(predicted_resolution, len(dataset.cases)),
            ambiguity_accuracy=_ratio(correct_ambiguity, expected_ambiguity),
            unresolved_accuracy=_ratio(correct_unresolved, expected_unresolved),
        ),
        cases=results,
    )


def semantic_ranking_diagnostics(
    dataset: ResolutionDataset,
    predictions: list[ResolutionPrediction],
    *,
    use_reranker_score: bool,
) -> SemanticRankingDiagnostics:
    if len(dataset.cases) != len(predictions):
        raise ValueError("resolution cases and predictions must have the same length")
    correct_margins: list[float] = []
    unresolved_top_scores: list[float] = []
    scored_resolved = correct_top_1 = scored_unresolved = 0
    for case, prediction in zip(dataset.cases, predictions, strict=True):
        scores = [
            candidate.reranker_score if use_reranker_score else candidate.similarity
            for candidate in prediction.candidates
        ]
        if not scores or scores[0] is None:
            continue
        numeric_scores = [score for score in scores if score is not None]
        if case.expected_entity_id is not None:
            scored_resolved += 1
            if prediction.candidates[0].entity.id == case.expected_entity_id:
                correct_top_1 += 1
                second_score = numeric_scores[1] if len(numeric_scores) > 1 else 0.0
                correct_margins.append(numeric_scores[0] - second_score)
        elif case.expected_outcome is ResolutionOutcome.UNRESOLVED:
            scored_unresolved += 1
            unresolved_top_scores.append(numeric_scores[0])
    return SemanticRankingDiagnostics(
        scored_resolved_case_count=scored_resolved,
        correct_top_1_count=correct_top_1,
        average_correct_top_1_margin=_average(correct_margins),
        minimum_correct_top_1_margin=min(correct_margins) if correct_margins else None,
        scored_unresolved_case_count=scored_unresolved,
        average_unresolved_top_score=_average(unresolved_top_scores),
        maximum_unresolved_top_score=max(unresolved_top_scores) if unresolved_top_scores else None,
    )


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None
