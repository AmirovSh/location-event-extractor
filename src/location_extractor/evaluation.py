from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field

from location_extractor.domain import Certainty, LocationEventCandidate, LocationRelation


class ExpectedEvent(BaseModel):
    person_mention: str
    location_mention: str
    relation: LocationRelation
    certainty: Certainty


class EvaluationCase(BaseModel):
    text: str
    events: list[ExpectedEvent] = Field(default_factory=list)


class EvaluationCounts(BaseModel):
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int


class EvaluationMetrics(BaseModel):
    event_detection_precision: float
    event_detection_recall: float
    event_detection_f1: float
    person_accuracy: float
    location_accuracy: float
    relation_accuracy: float
    certainty_accuracy: float
    whole_event_precision: float
    whole_event_recall: float
    whole_event_f1: float
    abstention_accuracy: float


class EvaluationReport(BaseModel):
    case_count: int
    expected_event_count: int
    predicted_event_count: int
    validator_rejection_count: int = 0
    provider_error_count: int = 0
    detection: EvaluationCounts
    metrics: EvaluationMetrics


def load_evaluation_cases(path: Path) -> list[EvaluationCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [EvaluationCase.model_validate(item) for item in payload]


def evaluate_predictions(
    cases: list[EvaluationCase],
    predictions: list[list[LocationEventCandidate]],
    *,
    validator_rejection_count: int = 0,
    provider_error_count: int = 0,
) -> EvaluationReport:
    if len(cases) != len(predictions):
        raise ValueError("cases and predictions must have the same length")

    true_positive = false_positive = false_negative = true_negative = 0
    expected_total = predicted_total = exact_matches = 0
    person_matches = location_matches = relation_matches = certainty_matches = 0
    abstention_total = abstention_matches = 0

    for case, predicted in zip(cases, predictions, strict=True):
        expected = case.events
        expected_present = bool(expected)
        predicted_present = bool(predicted)
        if expected_present and predicted_present:
            true_positive += 1
        elif predicted_present:
            false_positive += 1
        elif expected_present:
            false_negative += 1
        else:
            true_negative += 1

        if not expected_present:
            abstention_total += 1
            abstention_matches += int(not predicted_present)

        expected_total += len(expected)
        predicted_total += len(predicted)
        exact_matches += _exact_match_count(expected, predicted)

        for expected_event, predicted_event in _align_events(expected, predicted):
            if predicted_event is None:
                continue
            person_matches += int(
                _normalized(expected_event.person_mention)
                == _normalized(predicted_event.person_mention)
            )
            location_matches += int(
                _normalized(expected_event.location_mention)
                == _normalized(predicted_event.location_mention)
            )
            relation_matches += int(expected_event.relation is predicted_event.relation)
            certainty_matches += int(expected_event.certainty is predicted_event.certainty)

    detection_precision = _ratio(true_positive, true_positive + false_positive)
    detection_recall = _ratio(true_positive, true_positive + false_negative)
    event_precision = _ratio(exact_matches, predicted_total)
    event_recall = _ratio(exact_matches, expected_total)
    return EvaluationReport(
        case_count=len(cases),
        expected_event_count=expected_total,
        predicted_event_count=predicted_total,
        validator_rejection_count=validator_rejection_count,
        provider_error_count=provider_error_count,
        detection=EvaluationCounts(
            true_positive=true_positive,
            false_positive=false_positive,
            false_negative=false_negative,
            true_negative=true_negative,
        ),
        metrics=EvaluationMetrics(
            event_detection_precision=detection_precision,
            event_detection_recall=detection_recall,
            event_detection_f1=_f1(detection_precision, detection_recall),
            person_accuracy=_ratio(person_matches, expected_total),
            location_accuracy=_ratio(location_matches, expected_total),
            relation_accuracy=_ratio(relation_matches, expected_total),
            certainty_accuracy=_ratio(certainty_matches, expected_total),
            whole_event_precision=event_precision,
            whole_event_recall=event_recall,
            whole_event_f1=_f1(event_precision, event_recall),
            abstention_accuracy=_ratio(abstention_matches, abstention_total),
        ),
    )


def _align_events(
    expected: list[ExpectedEvent], predicted: list[LocationEventCandidate]
) -> list[tuple[ExpectedEvent, LocationEventCandidate | None]]:
    available = list(predicted)
    aligned: list[tuple[ExpectedEvent, LocationEventCandidate | None]] = []
    for expected_event in expected:
        if not available:
            aligned.append((expected_event, None))
            continue
        best_index = max(
            range(len(available)),
            key=lambda index: _matching_field_count(expected_event, available[index]),
        )
        aligned.append((expected_event, available.pop(best_index)))
    return aligned


def _matching_field_count(expected: ExpectedEvent, predicted: LocationEventCandidate) -> int:
    return sum(
        (
            _normalized(expected.person_mention) == _normalized(predicted.person_mention),
            _normalized(expected.location_mention) == _normalized(predicted.location_mention),
            expected.relation is predicted.relation,
            expected.certainty is predicted.certainty,
        )
    )


def _exact_match_count(
    expected: list[ExpectedEvent], predicted: list[LocationEventCandidate]
) -> int:
    expected_counts = Counter(_expected_key(event) for event in expected)
    predicted_counts = Counter(_predicted_key(event) for event in predicted)
    return sum((expected_counts & predicted_counts).values())


def _expected_key(event: ExpectedEvent) -> tuple[str, str, LocationRelation, Certainty]:
    return (
        _normalized(event.person_mention),
        _normalized(event.location_mention),
        event.relation,
        event.certainty,
    )


def _predicted_key(
    event: LocationEventCandidate,
) -> tuple[str, str, LocationRelation, Certainty]:
    return (
        _normalized(event.person_mention),
        _normalized(event.location_mention),
        event.relation,
        event.certainty,
    )


def _normalized(value: str | None) -> str:
    return value.strip().casefold() if value else ""


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0
