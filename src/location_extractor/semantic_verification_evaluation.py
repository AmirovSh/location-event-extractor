from __future__ import annotations

from pydantic import BaseModel

from location_extractor.resolution import VerificationVerdict


class PairVerificationPrediction(BaseModel):
    expected: VerificationVerdict
    predicted: VerificationVerdict


class VerificationMetrics(BaseModel):
    pair_count: int
    pair_accuracy: float
    same_entity_precision: float
    same_entity_recall: float
    different_entity_accuracy: float
    uncertain_rate: float


def score_pair_verifications(
    predictions: list[PairVerificationPrediction],
) -> VerificationMetrics:
    correct = sum(item.predicted is item.expected for item in predictions)
    expected_same = sum(item.expected is VerificationVerdict.SAME_ENTITY for item in predictions)
    predicted_same = sum(item.predicted is VerificationVerdict.SAME_ENTITY for item in predictions)
    correct_same = sum(
        item.expected is VerificationVerdict.SAME_ENTITY
        and item.predicted is VerificationVerdict.SAME_ENTITY
        for item in predictions
    )
    expected_different = sum(
        item.expected is VerificationVerdict.DIFFERENT_ENTITY for item in predictions
    )
    correct_different = sum(
        item.expected is VerificationVerdict.DIFFERENT_ENTITY
        and item.predicted is VerificationVerdict.DIFFERENT_ENTITY
        for item in predictions
    )
    uncertain = sum(item.predicted is VerificationVerdict.UNCERTAIN for item in predictions)
    return VerificationMetrics(
        pair_count=len(predictions),
        pair_accuracy=_ratio(correct, len(predictions)),
        same_entity_precision=_ratio(correct_same, predicted_same),
        same_entity_recall=_ratio(correct_same, expected_same),
        different_entity_accuracy=_ratio(correct_different, expected_different),
        uncertain_rate=_ratio(uncertain, len(predictions)),
    )


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0
