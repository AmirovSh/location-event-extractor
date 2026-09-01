from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from openai import AsyncOpenAI, DefaultAsyncHttpxClient, OpenAIError

from location_extractor.application import ExtractionProviderError
from location_extractor.domain import ExtractionResult, ParsedMessage


class OpenAIResponsesExtractor:
    provider = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        prompt_version: str,
        system_prompt: str,
        base_url: str | None = None,
        allow_insecure_http: bool = False,
        trust_env: bool = True,
        api_mode: Literal["responses", "chat_completions"] = "responses",
        max_output_tokens: int = 1200,
        enable_thinking: bool | None = None,
        temperature: float = 0,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if base_url and urlparse(base_url).scheme == "http" and not allow_insecure_http:
            raise ValueError("plain HTTP LLM endpoint requires LOCATION_ALLOW_INSECURE_HTTP=true")
        self.model = model
        self.prompt_version = prompt_version
        self.system_prompt = system_prompt
        self.api_mode = api_mode
        self.max_output_tokens = max_output_tokens
        self.enable_thinking = enable_thinking
        self.temperature = temperature
        self.client = client or AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
            http_client=DefaultAsyncHttpxClient(trust_env=trust_env),
        )

    async def extract(self, message: ParsedMessage) -> ExtractionResult:
        versioned_prompt = f"{self.system_prompt}\nPrompt version: {self.prompt_version}"
        try:
            if self.api_mode == "chat_completions":
                completion = await self.client.chat.completions.parse(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": versioned_prompt,
                        },
                        {
                            "role": "user",
                            "content": (
                                f"message_id: {message.message_id}\n"
                                f"sent_at: {message.sent_at.isoformat()}\n"
                                f"text: {message.text}"
                            ),
                        },
                    ],
                    response_format=ExtractionResult,
                    max_completion_tokens=self.max_output_tokens,
                    temperature=self.temperature,
                    extra_body=(
                        {"chat_template_kwargs": {"enable_thinking": self.enable_thinking}}
                        if self.enable_thinking is not None
                        else None
                    ),
                )
                parsed = completion.choices[0].message.parsed
            else:
                response = await self.client.responses.parse(
                    model=self.model,
                    instructions=versioned_prompt,
                    input=(
                        f"message_id: {message.message_id}\n"
                        f"sent_at: {message.sent_at.isoformat()}\n"
                        f"text: {message.text}"
                    ),
                    text_format=ExtractionResult,
                )
                parsed = response.output_parsed
        except OpenAIError as exc:
            raise ExtractionProviderError("location extraction provider failed") from exc
        if parsed is None:
            raise ExtractionProviderError("provider returned no structured extraction")
        return parsed
