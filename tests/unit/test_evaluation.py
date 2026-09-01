from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from location_extractor.application import ExtractionProviderError
from location_extractor.domain import ExtractionResult, LocationEventCandidate, ParsedMessage
from location_extractor.evaluation import (
    EvaluationCase,
    EvaluationCategory,
    ExpectedEvent,
    evaluate_predictions,
    load_evaluation_cases,
    summarize_performance,
)
from location_extractor.validation import CandidateValidator
from scripts.run_live_eval import (
    _execute_cases,
    _extract_with_retries,
    _provider_error_category,
    _select_cases,
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
    assert report.evaluated_case_count == 2


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


def test_provider_error_cases_are_excluded_from_semantic_metrics() -> None:
    cases = [
        EvaluationCase(text="John likes London."),
        EvaluationCase(text="Mary likes Paris."),
    ]
    report = evaluate_predictions(
        cases,
        [[], []],
        provider_error_count=1,
        provider_error_indices={0},
    )
    assert report.case_count == 2
    assert report.evaluated_case_count == 1
    assert report.detection.true_negative == 1
    assert report.metrics.abstention_accuracy == 1


def test_provider_error_index_must_reference_a_case() -> None:
    with pytest.raises(ValueError, match="provider error index is outside the case range"):
        evaluate_predictions(
            [EvaluationCase(text="John likes London.")],
            [[]],
            provider_error_indices={1},
        )


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
    assert len(cases) == 64
    assert all(case.text.isascii() for case in cases)
    assert any(len(case.events) > 1 for case in cases)
    assert any(not case.events for case in cases)
    relations = {event.relation.value for case in cases for event in case.events}
    certainties = {event.certainty.value for case in cases for event in case.events}
    assert {"AT", "TO", "FROM", "LEFT", "ARRIVED", "NEAR"} <= relations
    assert {"ASSERTED", "PROBABLE", "POSSIBLE", "NEGATED", "PLANNED"} <= certainties
    assert {case.category for case in cases} == set(EvaluationCategory)
    assert all(
        sum(case.category is category for case in cases) >= 5 for category in EvaluationCategory
    )


def test_report_separates_metrics_by_dataset_category() -> None:
    cases = [
        EvaluationCase(
            text="John is in London.",
            category=EvaluationCategory.PRESENCE,
            events=[expected("John", "London")],
        ),
        EvaluationCase(
            text="Mary bought a ticket to Paris.",
            category=EvaluationCategory.TRAVEL_CONTEXT,
        ),
    ]
    report = evaluate_predictions(cases, [[candidate("John", "London")], []])

    assert set(report.categories) == {
        EvaluationCategory.PRESENCE,
        EvaluationCategory.TRAVEL_CONTEXT,
    }
    assert report.categories[EvaluationCategory.PRESENCE].metrics.whole_event_f1 == 1
    assert report.categories[EvaluationCategory.TRAVEL_CONTEXT].metrics.abstention_accuracy == 1


def test_live_eval_can_select_categories_without_reordering_cases() -> None:
    cases = load_evaluation_cases(FIXTURE_PATH)
    selected = _select_cases(cases, ["hypothetical", "travel_context"])

    assert selected
    assert {case.category for case in selected} == {
        EvaluationCategory.HYPOTHETICAL,
        EvaluationCategory.TRAVEL_CONTEXT,
    }
    assert selected == [
        case
        for case in cases
        if case.category in {EvaluationCategory.HYPOTHETICAL, EvaluationCategory.TRAVEL_CONTEXT}
    ]


class FlakyExtractor:
    provider = "fake"
    model = "fixture"

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def extract(self, message: ParsedMessage) -> ExtractionResult:
        self.calls += 1
        if self.calls <= self.failures:
            raise ExtractionProviderError("temporary failure")
        return ExtractionResult()


@pytest.mark.parametrize(("failures", "retries", "expected_attempts"), [(0, 1, 1), (1, 1, 2)])
async def test_live_eval_retries_provider_failures(
    failures: int, retries: int, expected_attempts: int
) -> None:
    extractor = FlakyExtractor(failures)
    message = ParsedMessage(
        conversation_id="eval",
        message_id="case",
        sent_at=datetime.fromisoformat("2026-08-31T10:15:00+05:00"),
        text="John is in London.",
    )
    _, attempts = await _extract_with_retries(extractor, message, case_retries=retries)
    assert attempts == expected_attempts
    assert extractor.calls == expected_attempts


async def test_live_eval_stops_after_retry_budget() -> None:
    extractor = FlakyExtractor(failures=2)
    message = ParsedMessage(
        conversation_id="eval",
        message_id="case",
        sent_at=datetime.fromisoformat("2026-08-31T10:15:00+05:00"),
        text="John is in London.",
    )
    with pytest.raises(ExtractionProviderError):
        await _extract_with_retries(extractor, message, case_retries=1)
    assert extractor.calls == 2


def test_provider_error_category_uses_bounded_exception_type() -> None:
    try:
        raise TimeoutError("sensitive provider details")
    except TimeoutError as cause:
        error = ExtractionProviderError("provider failed")
        error.__cause__ = cause
    assert _provider_error_category(error) == "TimeoutError"


def test_empty_performance_summary_is_zeroed() -> None:
    summary = summarize_performance([], [], total_duration_ms=0)
    assert set(summary.model_dump().values()) == {0}


def test_performance_summary_rejects_inconsistent_inputs() -> None:
    with pytest.raises(ValueError, match="latencies and attempts must have the same length"):
        summarize_performance([10], [], total_duration_ms=10)


class ConcurrentExtractor:
    provider = "fake"
    model = "concurrency"

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def extract(self, message: ParsedMessage) -> ExtractionResult:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            delay = 0.03 if message.message_id == "eval-1" else 0.01
            await asyncio.sleep(delay)
            return ExtractionResult()
        finally:
            self.active -= 1


async def test_concurrent_execution_is_bounded_and_preserves_dataset_order() -> None:
    cases = [EvaluationCase(text=f"Message {index}.") for index in range(4)]
    extractor = ConcurrentExtractor()
    executions = await _execute_cases(
        cases,
        extractor,
        CandidateValidator(),
        case_retries=0,
        concurrency=2,
    )
    assert extractor.max_active == 2
    assert [execution.index for execution in executions] == [0, 1, 2, 3]
    assert [execution.detail["text"] for execution in executions] == [case.text for case in cases]


async def test_concurrent_execution_requires_positive_limit() -> None:
    with pytest.raises(ValueError, match="concurrency must be positive"):
        await _execute_cases(
            [EvaluationCase(text="Message.")],
            ConcurrentExtractor(),
            CandidateValidator(),
            case_retries=0,
            concurrency=0,
        )
