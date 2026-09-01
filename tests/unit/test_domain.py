from __future__ import annotations

import pytest
from pydantic import ValidationError

from location_extractor.domain import ParsedMessage


def test_message_requires_timezone() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        ParsedMessage(
            conversation_id="conv",
            message_id="msg",
            sent_at="2026-08-31T10:15:00",
            text="Иван в Алматы.",
        )
