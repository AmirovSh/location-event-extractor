from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from location_extractor.application import ExtractionProviderError  # noqa: E402
from location_extractor.config import Settings  # noqa: E402
from location_extractor.config_loader import load_extraction_prompt  # noqa: E402
from location_extractor.domain import LocationEventCandidate, ParsedMessage  # noqa: E402
from location_extractor.evaluation import (  # noqa: E402
    evaluate_predictions,
    load_evaluation_cases,
)
from location_extractor.openai_adapter import OpenAIResponsesExtractor  # noqa: E402
from location_extractor.validation import CandidateValidator  # noqa: E402

DEFAULT_DATASET = PROJECT_ROOT / "tests" / "fixtures" / "extraction_cases.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "evaluation-results" / "live-eval.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the opt-in live extraction evaluation")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


async def run(dataset: Path, output: Path) -> None:
    settings = Settings()
    if not settings.openai_api_key:
        raise SystemExit("OpenAI API key is not configured")

    cases = load_evaluation_cases(dataset)
    extractor = OpenAIResponsesExtractor(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        allow_insecure_http=settings.allow_insecure_http,
        trust_env=settings.openai_trust_env,
        api_mode=settings.openai_api_mode,
        max_output_tokens=settings.openai_max_output_tokens,
        enable_thinking=settings.openai_enable_thinking,
        temperature=settings.openai_temperature,
        model=settings.openai_model,
        timeout_seconds=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
        prompt_version=settings.prompt_version,
        system_prompt=load_extraction_prompt()[1],
    )
    validator = CandidateValidator()
    predictions: list[list[LocationEventCandidate]] = []
    details: list[dict[str, object]] = []
    rejection_count = provider_error_count = 0

    for index, case in enumerate(cases, start=1):
        message = ParsedMessage(
            conversation_id="live-eval",
            message_id=f"eval-{index}",
            sent_at=datetime.now(UTC),
            text=case.text,
            locale="en",
        )
        error: str | None = None
        raw_events: list[LocationEventCandidate] = []
        accepted_events: list[LocationEventCandidate] = []
        rejections: list[str] = []
        try:
            raw_events = (await extractor.extract(message)).events
            for candidate in raw_events:
                validation = validator.validate(message, candidate)
                if validation.accepted:
                    accepted_events.append(validation.candidate)
                else:
                    rejection_count += 1
                    rejections.append(validation.reason.value if validation.reason else "UNKNOWN")
        except ExtractionProviderError as exc:
            provider_error_count += 1
            error = str(exc)

        predictions.append(accepted_events)
        details.append(
            {
                "text": case.text,
                "expected": [event.model_dump(mode="json") for event in case.events],
                "raw_predictions": [event.model_dump(mode="json") for event in raw_events],
                "accepted_predictions": [
                    event.model_dump(mode="json") for event in accepted_events
                ],
                "rejections": rejections,
                "provider_error": error,
            }
        )

    report = evaluate_predictions(
        cases,
        predictions,
        validator_rejection_count=rejection_count,
        provider_error_count=provider_error_count,
    )
    payload = {
        "metadata": {
            "model": settings.openai_model,
            "extractor_version": settings.extractor_version,
            "schema_version": settings.schema_version,
            "prompt_version": settings.prompt_version,
            "dataset": str(dataset),
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "report": report.model_dump(mode="json"),
        "cases": details,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    print(f"Detailed report: {output}")


if __name__ == "__main__":
    arguments = parse_args()
    asyncio.run(run(arguments.dataset, arguments.output))
