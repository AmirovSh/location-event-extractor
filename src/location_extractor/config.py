from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from location_extractor.config_loader import load_application_config

_CONFIG = load_application_config()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LOCATION_", env_file=(".env", ".env.runtime"), extra="ignore"
    )

    database_url: str = _CONFIG["database"]["url"]
    extractor_backend: str = _CONFIG["extraction"]["backend"]
    extractor_version: str = _CONFIG["extraction"]["extractor_version"]
    schema_version: str = _CONFIG["extraction"]["schema_version"]
    prompt_version: str = _CONFIG["extraction"]["prompt_version"]
    openai_api_key: str | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices("LOCATION_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    openai_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LOCATION_OPENAI_BASE_URL", "SEMANTIC_GRAPH_LLM_BASE_URL"),
    )
    allow_insecure_http: bool = _CONFIG["openai"]["allow_insecure_http"]
    openai_trust_env: bool = _CONFIG["openai"]["trust_env"]
    openai_api_mode: Literal["responses", "chat_completions"] = _CONFIG["openai"]["api_mode"]
    openai_max_output_tokens: int = Field(
        default=_CONFIG["openai"]["max_output_tokens"], ge=128, le=16_384
    )
    openai_enable_thinking: bool | None = None
    openai_temperature: float = Field(default=_CONFIG["openai"]["temperature"], ge=0, le=2)
    openai_model: str = _CONFIG["openai"]["model"]
    openai_timeout_seconds: float = Field(
        default=_CONFIG["openai"]["timeout_seconds"], gt=0, le=120
    )
    openai_max_retries: int = Field(default=_CONFIG["openai"]["max_retries"], ge=0, le=5)
    embedding_api_key: str | None = Field(default=None, repr=False)
    embedding_base_url: str | None = None
    embedding_model: str = _CONFIG["embedding"]["model"]
    embedding_dimensions: int | None = Field(default=None, ge=1, le=16_384)
    embedding_timeout_seconds: float = Field(
        default=_CONFIG["embedding"]["timeout_seconds"], gt=0, le=120
    )
    embedding_max_retries: int = Field(default=_CONFIG["embedding"]["max_retries"], ge=0, le=5)
    embedding_top_k: int = Field(default=_CONFIG["embedding"]["top_k"], ge=1, le=100)
    embedding_corpus_limit: int = Field(
        default=_CONFIG["embedding"]["corpus_limit"], ge=1, le=100_000
    )
    reranker_api_key: str | None = Field(default=None, repr=False)
    reranker_base_url: str | None = None
    reranker_model: str = _CONFIG["reranker"]["model"]
    reranker_timeout_seconds: float = Field(
        default=_CONFIG["reranker"]["timeout_seconds"], gt=0, le=120
    )
    reranker_max_retries: int = Field(default=_CONFIG["reranker"]["max_retries"], ge=0, le=5)
    reranker_top_n: int = Field(default=_CONFIG["reranker"]["top_n"], ge=1, le=100)
    resolution_enabled: bool = _CONFIG["resolution"]["enabled"]
    resolution_verifier_model: str = _CONFIG["resolution"]["verifier_model"]
    resolution_verifier_concurrency: int = Field(
        default=_CONFIG["resolution"]["verifier_concurrency"], ge=1, le=16
    )
    log_level: str = _CONFIG["observability"]["log_level"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
