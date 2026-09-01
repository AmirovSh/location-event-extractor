from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from location_extractor.config import Settings
from location_extractor.domain import ExtractionResult, LocationEventCandidate, ParsedMessage
from location_extractor.openai_adapter import OpenAIResponsesExtractor


class FakeResponses:
    def __init__(self, parsed: ExtractionResult) -> None:
        self.parsed = parsed
        self.kwargs: dict[str, Any] = {}

    async def parse(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return SimpleNamespace(output_parsed=self.parsed)


class FakeChatCompletions:
    def __init__(self, parsed: ExtractionResult) -> None:
        self.parsed = parsed
        self.kwargs: dict[str, Any] = {}

    async def parse(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        message = SimpleNamespace(parsed=self.parsed)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


async def test_adapter_uses_typed_responses_output() -> None:
    responses = FakeResponses(
        ExtractionResult(
            events=[
                LocationEventCandidate(
                    person_mention="John",
                    location_mention="London",
                    relation="AT",
                    certainty="ASSERTED",
                    evidence_text="John is in London",
                )
            ]
        )
    )
    client = SimpleNamespace(responses=responses)
    adapter = OpenAIResponsesExtractor(
        api_key="not-used",
        model="test-model",
        timeout_seconds=1,
        max_retries=0,
        prompt_version="p1",
        system_prompt="Do not choose database ids.",
        client=client,
    )
    result = await adapter.extract(
        ParsedMessage(
            conversation_id="c",
            message_id="m",
            sent_at=datetime.fromisoformat("2026-08-31T10:15:00+05:00"),
            text="John is in London",
        )
    )
    assert result.events[0].relation.value == "AT"
    assert responses.kwargs["text_format"] is ExtractionResult
    assert "database ids" in responses.kwargs["instructions"]


def test_plain_http_requires_explicit_opt_in() -> None:
    with pytest.raises(ValueError, match="ALLOW_INSECURE_HTTP"):
        OpenAIResponsesExtractor(
            api_key="secret",
            model="test-model",
            timeout_seconds=1,
            max_retries=0,
            prompt_version="p1",
            system_prompt="test prompt",
            base_url="http://llm.internal/v1",
        )


def test_runtime_environment_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "runtime-secret")
    monkeypatch.setenv("SEMANTIC_GRAPH_LLM_BASE_URL", "http://llm.internal/v1")
    settings = Settings(_env_file=None)
    assert settings.openai_api_key == "runtime-secret"
    assert settings.openai_base_url == "http://llm.internal/v1"


async def test_chat_completions_compatibility_mode() -> None:
    parsed = ExtractionResult()
    completions = FakeChatCompletions(parsed)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    adapter = OpenAIResponsesExtractor(
        api_key="not-used",
        model="test-model",
        timeout_seconds=1,
        max_retries=0,
        prompt_version="p1",
        system_prompt="test prompt",
        api_mode="chat_completions",
        enable_thinking=False,
        client=client,
    )
    result = await adapter.extract(
        ParsedMessage(
            conversation_id="c",
            message_id="m",
            sent_at=datetime.fromisoformat("2026-08-31T10:15:00+05:00"),
            text="I like London.",
        )
    )
    assert result == parsed
    assert completions.kwargs["response_format"] is ExtractionResult
    assert completions.kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert completions.kwargs["temperature"] == 0
