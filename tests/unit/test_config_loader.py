from __future__ import annotations

from location_extractor.config import Settings
from location_extractor.config_loader import load_extraction_prompt


def test_database_default_comes_from_application_config() -> None:
    settings = Settings(_env_file=None)
    assert settings.database_url.endswith("localhost:55432/location")


def test_prompt_is_external_and_versioned() -> None:
    version, prompt = load_extraction_prompt()
    assert version == "mvp-2"
    assert "person_reference" in prompt
    assert "physical person-location events" in prompt
