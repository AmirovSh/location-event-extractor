from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

if TYPE_CHECKING:
    from location_extractor.resolution_evaluation import ResolutionEvaluationReport

PROJECT_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

DEFAULT_DATASET = PROJECT_ROOT / "tests" / "fixtures" / "resolution_cases.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "evaluation-results" / "resolution-baseline.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic entity-resolution baseline")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def run(dataset_path: Path) -> ResolutionEvaluationReport:
    from location_extractor.db import Base
    from location_extractor.resolution import DeterministicResolutionPolicy
    from location_extractor.resolution_evaluation import (
        evaluate_resolution_dataset,
        load_resolution_dataset,
        seed_resolution_dataset,
    )
    from location_extractor.resolution_repository import (
        SqlAlchemyEntityResolutionRepository,
    )

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyEntityResolutionRepository(sessionmaker(engine, expire_on_commit=False))
    dataset = load_resolution_dataset(dataset_path)
    seed_resolution_dataset(repository, dataset)
    return evaluate_resolution_dataset(
        repository,
        DeterministicResolutionPolicy(),
        dataset,
    )


def main() -> None:
    from location_extractor.resolution import DeterministicResolutionPolicy

    arguments = parse_args()
    report = run(arguments.dataset)
    payload = {
        "metadata": {
            "retriever": "scoped-exact-alias-v1",
            "policy": DeterministicResolutionPolicy.version,
            "dataset": str(arguments.dataset),
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "report": report.model_dump(mode="json"),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"Detailed report: {arguments.output}")


if __name__ == "__main__":
    main()
