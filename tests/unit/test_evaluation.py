from __future__ import annotations

from pathlib import Path

import pytest

from location_extractor.domain import LocationEventCandidate
from location_extractor.evaluation import (
    EvaluationCase,
    ExpectedEvent,
    evaluate_predictions,
    load_evaluation_cases,
)

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "extraction_cases.json"


def candidate(
    person: str, location: str, relation: str = "AT", certainty: str = "ASSERTED"
) -> LocationEventCandidate:
    return LocationEventCandidate(
        person_mention=person,
        location_mention=location,
        relation=relation,
        certainty=certainty,
        evidence_text=f"{person} in {location}",
    )


def expected(
    person: str, location: str, relation: str = "AT", certainty: str = "ASSERTED"
) -> ExpectedEvent:
    return ExpectedEvent(
        person_mention=person,
        location_mention=location,
        relation=relation,
        certainty=certainty,
    )


def test_perfect_predictions_score_one() -> None:
    cases = [
        EvaluationCase(
            text="John is in London.",
            events=[expected("John", "London")],
        ),
        EvaluationCase(text="John likes London."),
    ]
    report = evaluate_predictions(cases, [[candidate("John", "London")], []])
    assert report.metrics.event_detection_f1 == 1
    assert report.metrics.whole_event_f1 == 1
    assert report.metrics.person_accuracy == 1
    assert report.metrics.abstention_accuracy == 1


def test_metrics_count_false_positive_missing_event_and_field_errors() -> None:
    cases = [
        EvaluationCase(
            text="John is in London.",
            events=[expected("John", "London")],
        ),
        EvaluationCase(text="Mary likes Paris."),
        EvaluationCase(
            text="Peter arrived in Astana.",
            events=[expected("Peter", "Astana", "ARRIVED")],
        ),
    ]
    predictions = [
        [candidate("John", "Paris")],
        [candidate("Mary", "Paris")],
        [],
    ]
    report = evaluate_predictions(
        cases,
        predictions,
        validator_rejection_count=2,
        provider_error_count=1,
    )
    assert report.detection.model_dump() == {
        "true_positive": 1,
        "false_positive": 1,
        "false_negative": 1,
        "true_negative": 0,
    }
    assert report.metrics.event_detection_precision == 0.5
    assert report.metrics.event_detection_recall == 0.5
    assert report.metrics.person_accuracy == 0.5
    assert report.metrics.location_accuracy == 0
    assert report.metrics.whole_event_f1 == 0
    assert report.metrics.abstention_accuracy == 0
    assert report.validator_rejection_count == 2
    assert report.provider_error_count == 1


def test_event_order_does_not_affect_exact_match() -> None:
    cases = [
        EvaluationCase(
            text="John is in London and Mary is in Paris.",
            events=[expected("John", "London"), expected("Mary", "Paris")],
        )
    ]
    report = evaluate_predictions(
        cases,
        [[candidate("Mary", "Paris"), candidate("John", "London")]],
    )
    assert report.metrics.whole_event_f1 == 1


def test_case_and_outer_whitespace_are_normalized() -> None:
    cases = [
        EvaluationCase(
            text="John is in London.",
            events=[expected("John", "London")],
        )
    ]
    report = evaluate_predictions(cases, [[candidate(" john ", "LONDON")]])
    assert report.metrics.whole_event_f1 == 1


def test_case_and_prediction_lengths_must_match() -> None:
    with pytest.raises(ValueError, match="cases and predictions must have the same length"):
        evaluate_predictions([EvaluationCase(text="John is in London.")], [])


def test_fixture_dataset_is_english_only_and_covers_core_contrasts() -> None:
    cases = load_evaluation_cases(FIXTURE_PATH)
    assert len(cases) >= 20
    assert all(case.text.isascii() for case in cases)
    assert any(len(case.events) > 1 for case in cases)
    assert any(not case.events for case in cases)
    relations = {event.relation.value for case in cases for event in case.events}
    certainties = {event.certainty.value for case in cases for event in case.events}
    assert {"AT", "TO", "FROM", "LEFT", "ARRIVED", "NEAR"} <= relations
    assert {"ASSERTED", "PROBABLE", "POSSIBLE", "NEGATED", "PLANNED"} <= certainties
