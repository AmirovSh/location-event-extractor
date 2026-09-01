from __future__ import annotations

from location_extractor.config import Settings


def test_database_default_comes_from_application_config() -> None:
    settings = Settings(_env_file=None)
    assert settings.database_url.endswith("localhost:55432/location")
