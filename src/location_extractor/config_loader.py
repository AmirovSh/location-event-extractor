from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

CONFIG_DIRECTORY = Path(__file__).with_name("config_files")
APPLICATION_CONFIG_PATH = CONFIG_DIRECTORY / "application.toml"
PROMPT_CONFIG_PATH = CONFIG_DIRECTORY / "prompts.toml"


@lru_cache
def load_application_config(path: Path = APPLICATION_CONFIG_PATH) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


@lru_cache
def load_extraction_prompt(path: Path = PROMPT_CONFIG_PATH) -> tuple[str, str]:
    with path.open("rb") as stream:
        document = tomllib.load(stream)
    prompt = document["location_event_extraction"]
    version = str(prompt["version"]).strip()
    system = str(prompt["system"]).strip()
    if not version or not system:
        raise ValueError("location_event_extraction prompt and version must not be empty")
    return version, system
