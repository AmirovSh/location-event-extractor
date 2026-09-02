from __future__ import annotations

from typing import Literal, TypeVar
from urllib.parse import urlparse

from openai import AsyncOpenAI, DefaultAsyncHttpxClient, OpenAIError
from pydantic import BaseModel

from location_extractor.resolution import (
    CandidateSetVerification,
    EntityMention,
    PairwiseVerification,
    ResolutionCandidate,
)

StructuredVerification = TypeVar("StructuredVerification", bound=BaseModel)


class VerificationProviderError(RuntimeError):
    pass


class OpenAICompatiblePairwiseVerifier:
    provider = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        prompt_version: str,
        system_prompt: str,
        adjudication_prompt_version: str | None = None,
        adjudication_system_prompt: str | None = None,
        base_url: str | None = None,
        allow_insecure_http: bool = False,
        trust_env: bool = True,
        api_mode: Literal["responses", "chat_completions"] = "responses",
        max_output_tokens: int = 1024,
        enable_thinking: bool | None = None,
        temperature: float = 0,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if base_url and urlparse(base_url).scheme == "http" and not allow_insecure_http:
            raise ValueError(
                "plain HTTP verifier endpoint requires LOCATION_ALLOW_INSECURE_HTTP=true"
            )
        self.model = model
        self.prompt_version = prompt_version
        self.system_prompt = system_prompt
        self.adjudication_prompt_version = adjudication_prompt_version
        self.adjudication_system_prompt = adjudication_system_prompt
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

    async def verify(
        self, mention: EntityMention, candidate: ResolutionCandidate
    ) -> PairwiseVerification:
        return await self._parse_structured(
            _verification_input(mention, candidate),
            response_format=PairwiseVerification,
            system_prompt=self.system_prompt,
            prompt_version=self.prompt_version,
        )

    async def verify_candidate_set(
        self, mention: EntityMention, candidates: list[ResolutionCandidate]
    ) -> CandidateSetVerification:
        if not self.adjudication_system_prompt or not self.adjudication_prompt_version:
            raise ValueError("candidate-set adjudication prompt is not configured")
        return await self._parse_structured(
            _candidate_set_input(mention, candidates),
            response_format=CandidateSetVerification,
            system_prompt=self.adjudication_system_prompt,
            prompt_version=self.adjudication_prompt_version,
        )

    async def _parse_structured(
        self,
        user_input: str,
        *,
        response_format: type[StructuredVerification],
        system_prompt: str,
        prompt_version: str,
    ) -> StructuredVerification:
        prompt = f"{system_prompt}\nPrompt version: {prompt_version}"
        try:
            if self.api_mode == "chat_completions":
                completion = await self.client.chat.completions.parse(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": user_input},
                    ],
                    response_format=response_format,
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
                    instructions=prompt,
                    input=user_input,
                    text_format=response_format,
                )
                parsed = response.output_parsed
        except OpenAIError as exc:
            raise VerificationProviderError("entity verification provider failed") from exc
        if parsed is None:
            raise VerificationProviderError("provider returned no structured verification")
        return parsed


def _verification_input(mention: EntityMention, candidate: ResolutionCandidate) -> str:
    context = mention.context or "No additional context supplied."
    known_mentions = "; ".join(candidate.supporting_texts) or candidate.matched_alias
    return "\n".join(
        (
            f"Entity type: {mention.entity_type.value}",
            f"Mention: {mention.text}",
            f"Context: {context}",
            "Candidate profile:",
            f"Canonical name: {candidate.entity.display_name}",
            f"Known mentions: {known_mentions}",
        )
    )


def _candidate_set_input(mention: EntityMention, candidates: list[ResolutionCandidate]) -> str:
    profiles: list[str] = []
    for position, candidate in enumerate(candidates, start=1):
        known_mentions = "; ".join(candidate.supporting_texts) or candidate.matched_alias
        profiles.extend(
            (
                f"Candidate position: {position}",
                f"Canonical name: {candidate.entity.display_name}",
                f"Known mentions: {known_mentions}",
            )
        )
    return "\n".join(
        (
            f"Entity type: {mention.entity_type.value}",
            f"Mention: {mention.text}",
            f"Context: {mention.context or 'No additional context supplied.'}",
            "Candidate profiles:",
            *profiles,
        )
    )
