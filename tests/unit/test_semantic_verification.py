from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from location_extractor.resolution import (
    CandidateSetVerdict,
    CandidateSetVerification,
    CanonicalEntity,
    EntityMention,
    EntityType,
    PairwiseVerification,
    ResolutionCandidate,
    ResolutionConfidence,
    ResolutionFactor,
    ResolutionOutcome,
    ResolutionScope,
    VerificationVerdict,
    VerifiedResolutionPolicy,
)
from location_extractor.semantic_verification import OpenAICompatiblePairwiseVerifier
from location_extractor.semantic_verification_evaluation import (
    PairVerificationPrediction,
    score_pair_verifications,
)


def _candidate(entity_id: int, name: str) -> ResolutionCandidate:
    return ResolutionCandidate(
        entity=CanonicalEntity(
            id=UUID(int=entity_id),
            tenant_id="tenant-alpha",
            entity_type=EntityType.PERSON,
            display_name=name,
        ),
        matched_alias=name,
        supporting_texts=[name],
        factors=[ResolutionFactor.EMBEDDING_SIMILARITY],
        specificity=0,
        similarity=0.8,
    )


def _verification(
    verdict: VerificationVerdict,
    *,
    confidence: ResolutionConfidence = ResolutionConfidence.HIGH,
    insufficient: bool = False,
) -> PairwiseVerification:
    return PairwiseVerification(
        verdict=verdict,
        confidence=confidence,
        insufficient_context=insufficient,
    )


def test_policy_resolves_only_one_confirmed_candidate_with_rejected_competitors() -> None:
    mention = EntityMention(
        entity_type=EntityType.PERSON,
        text="Alex from operations",
        scope=ResolutionScope(tenant_id="tenant-alpha"),
    )
    candidates = [_candidate(1, "Alex Operations"), _candidate(2, "Alex Design")]
    decision = VerifiedResolutionPolicy().decide(
        mention,
        candidates,
        [
            _verification(VerificationVerdict.SAME_ENTITY),
            _verification(VerificationVerdict.DIFFERENT_ENTITY),
        ],
    )
    assert decision.outcome is ResolutionOutcome.RESOLVED
    assert decision.canonical_entity_id == candidates[0].entity.id


@pytest.mark.parametrize(
    "verifications, expected",
    [
        (
            [
                _verification(VerificationVerdict.SAME_ENTITY),
                _verification(VerificationVerdict.UNCERTAIN),
            ],
            ResolutionOutcome.RESOLVED,
        ),
        (
            [
                _verification(VerificationVerdict.SAME_ENTITY),
                _verification(VerificationVerdict.SAME_ENTITY),
            ],
            ResolutionOutcome.AMBIGUOUS,
        ),
        (
            [
                _verification(VerificationVerdict.DIFFERENT_ENTITY),
                _verification(VerificationVerdict.DIFFERENT_ENTITY),
            ],
            ResolutionOutcome.UNRESOLVED,
        ),
    ],
)
def test_policy_requires_exactly_one_confirmed_identity(
    verifications: list[PairwiseVerification], expected: ResolutionOutcome
) -> None:
    mention = EntityMention(
        entity_type=EntityType.PERSON,
        text="Alex",
        scope=ResolutionScope(tenant_id="tenant-alpha"),
    )
    decision = VerifiedResolutionPolicy().decide(
        mention, [_candidate(1, "Alex A"), _candidate(2, "Alex B")], verifications
    )
    assert decision.outcome is expected


def test_policy_uses_validated_candidate_position_for_comparative_adjudication() -> None:
    mention = EntityMention(
        entity_type=EntityType.PERSON,
        text="Alex from operations",
        scope=ResolutionScope(tenant_id="tenant-alpha"),
    )
    candidates = [_candidate(1, "Alex Operations"), _candidate(2, "Alex Design")]
    decision = VerifiedResolutionPolicy().decide(
        mention,
        candidates,
        [
            _verification(VerificationVerdict.SAME_ENTITY),
            _verification(VerificationVerdict.SAME_ENTITY),
        ],
        CandidateSetVerification(
            verdict=CandidateSetVerdict.UNIQUE_MATCH,
            selected_candidate_position=1,
            confidence=ResolutionConfidence.HIGH,
            insufficient_context=False,
        ),
    )
    assert decision.outcome is ResolutionOutcome.RESOLVED
    assert decision.canonical_entity_id == candidates[0].entity.id


class FakeChatCompletions:
    def __init__(self, parsed: PairwiseVerification) -> None:
        self.parsed = parsed
        self.kwargs: dict[str, object] = {}

    async def parse(self, **kwargs: object) -> object:
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=self.parsed))]
        )


async def test_adapter_uses_structured_output_without_database_ids() -> None:
    parsed = _verification(VerificationVerdict.SAME_ENTITY)
    completions = FakeChatCompletions(parsed)
    verifier = OpenAICompatiblePairwiseVerifier(
        api_key="not-used",
        model="test-model",
        timeout_seconds=1,
        max_retries=0,
        prompt_version="v1",
        system_prompt="Verify identity without database identifiers.",
        api_mode="chat_completions",
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    mention = EntityMention(
        entity_type=EntityType.PERSON,
        text="Alex from operations",
        context="Alex from operations approved the schedule.",
        scope=ResolutionScope(tenant_id="tenant-alpha"),
    )
    candidate = _candidate(99, "Alex Operations")
    result = await verifier.verify(mention, candidate)
    serialized_messages = str(completions.kwargs["messages"])
    assert result is parsed
    assert str(candidate.entity.id) not in serialized_messages
    assert "Alex from operations" in serialized_messages
    assert completions.kwargs["response_format"] is PairwiseVerification


def test_pair_verification_metrics_separate_precision_and_abstention() -> None:
    report = score_pair_verifications(
        [
            PairVerificationPrediction(
                expected=VerificationVerdict.SAME_ENTITY,
                predicted=VerificationVerdict.SAME_ENTITY,
            ),
            PairVerificationPrediction(
                expected=VerificationVerdict.DIFFERENT_ENTITY,
                predicted=VerificationVerdict.DIFFERENT_ENTITY,
            ),
            PairVerificationPrediction(
                expected=VerificationVerdict.DIFFERENT_ENTITY,
                predicted=VerificationVerdict.UNCERTAIN,
            ),
        ]
    )
    assert report.pair_count == 3
    assert report.same_entity_precision == 1
    assert report.same_entity_recall == 1
    assert report.uncertain_rate > 0
