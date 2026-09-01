from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from location_extractor.application import ExtractionProviderError  # noqa: E402
from location_extractor.config import Settings  # noqa: E402
from location_extractor.config_loader import load_extraction_prompt  # noqa: E402
from location_extractor.domain import ParsedMessage  # noqa: E402
from location_extractor.openai_adapter import OpenAIResponsesExtractor  # noqa: E402
from location_extractor.validation import CandidateValidator  # noqa: E402

CASES = (
    "John is in London now.",
    "Peter arrived in Astana.",
    "John is not in London.",
    "John said that Mary is in Boston.",
    "I like London.",
    "He is in London.",
)


async def main() -> None:
    settings = Settings()
    if not settings.openai_api_key:
        raise SystemExit("OpenAI API key is not configured")
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
    for index, text in enumerate(CASES, start=1):
        message = ParsedMessage(
            conversation_id="live-smoke",
            message_id=f"live-{index}",
            sent_at=datetime.now(UTC),
            text=text,
        )
        try:
            extraction = await extractor.extract(message)
        except ExtractionProviderError as exc:
            print(json.dumps({"text": text, "error": str(exc)}, ensure_ascii=False))
            continue
        validations = [validator.validate(message, candidate) for candidate in extraction.events]
        print(
            json.dumps(
                {
                    "text": text,
                    "events": [
                        candidate.model_dump(mode="json") for candidate in extraction.events
                    ],
                    "persistable": [result.accepted for result in validations],
                    "rejections": [
                        result.reason.value if result.reason else None for result in validations
                    ],
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
