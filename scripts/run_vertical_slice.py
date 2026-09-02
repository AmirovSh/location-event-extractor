from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

PROJECT_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

DEFAULT_INPUT = PROJECT_ROOT / "tests" / "fixtures" / "vertical_slice_messages.jsonl"
DEFAULT_ENTITIES = PROJECT_ROOT / "tests" / "fixtures" / "resolution_cases.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "evaluation-results" / "vertical-slice-report.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run extraction-to-resolution PostgreSQL slice")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--entities", type=Path, default=DEFAULT_ENTITIES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


async def run(arguments: argparse.Namespace) -> dict[str, Any]:
    from location_extractor.api import build_service
    from location_extractor.config import Settings
    from location_extractor.db import create_session_factory
    from location_extractor.domain import ParsedMessage
    from location_extractor.resolution_evaluation import (
        load_resolution_dataset,
        seed_resolution_dataset,
    )
    from location_extractor.resolution_repository import SqlAlchemyEntityResolutionRepository

    settings = Settings()
    if not settings.resolution_enabled:
        raise SystemExit("LOCATION_RESOLUTION_ENABLED must be true")
    repository = SqlAlchemyEntityResolutionRepository(create_session_factory(settings.database_url))
    seed_resolution_dataset(repository, load_resolution_dataset(arguments.entities))
    service = build_service(settings)
    rows = [
        json.loads(line)
        for line in arguments.input.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    details: list[dict[str, Any]] = []
    correct_person = correct_location = 0
    for row in rows:
        message = ParsedMessage.model_validate(row["message"])
        result = await service.process(message)
        person_id = location_id = None
        if result.resolutions:
            person_id = result.resolutions[0].person.canonical_entity_id
            location_id = result.resolutions[0].location.canonical_entity_id
        expected_person = _optional_uuid(row.get("expected_person_entity_id"))
        expected_location = _optional_uuid(row.get("expected_location_entity_id"))
        correct_person += int(person_id == expected_person)
        correct_location += int(location_id == expected_location)
        details.append(
            {
                "message_id": message.message_id,
                "status": result.status.value,
                "replayed": result.replayed,
                "event_count": sum(outcome.persisted for outcome in result.outcomes),
                "person_entity_id": str(person_id) if person_id else None,
                "location_entity_id": str(location_id) if location_id else None,
                "expected_person_entity_id": str(expected_person) if expected_person else None,
                "expected_location_entity_id": (
                    str(expected_location) if expected_location else None
                ),
            }
        )
    count = len(rows)
    return {
        "summary": {
            "message_count": count,
            "person_resolution_accuracy": correct_person / count if count else 0.0,
            "location_resolution_accuracy": correct_location / count if count else 0.0,
        },
        "messages": details,
    }


def _optional_uuid(value: object) -> UUID | None:
    return UUID(str(value)) if value is not None else None


async def main() -> None:
    arguments = parse_args()
    payload = await run(arguments)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(f"Detailed report: {arguments.output}")


if __name__ == "__main__":
    asyncio.run(main())
