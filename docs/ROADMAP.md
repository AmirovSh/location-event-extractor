# Roadmap

## Current MVP

Implemented:

- typed request, candidate, event, rejection, and response contracts;
- FastAPI extraction endpoint and health endpoint;
- provider-independent extractor port, fake extractor, and OpenAI-compatible adapter;
- strict structured output with versioned external prompt;
- deterministic validation of explicitness, semantics, and evidence provenance;
- multiple candidates, typed outcomes, and idempotent replay;
- PostgreSQL persistence, Alembic migrations, and Docker Compose setup;
- unit, API, adapter, repository, and PostgreSQL integration tests;
- deterministic English evaluation metrics and an opt-in live evaluation command.

Not active in the current workflow:

- Stanza/NLP pre-filter (`AlwaysPassDetector` is used);
- a recorded live-model baseline for the current prompt/model pair.

## Next

1. Record and review the first live English baseline for the current prompt/model pair.
2. Expand the anonymized English fixture set as production-like edge cases are discovered.
3. Consider a Stanza or lightweight detector only if measured recall is safe and LLM cost/latency
   makes filtering worthwhile.

## Post-MVP

1. Canonical location registry, aliases, hierarchy, and auditable resolution.
2. Canonical person registry, aliases, and explicit ambiguity.
3. Bounded person coreference over dialogue context.
4. Location/deictic coreference over dialogue context.
5. Relative-time normalization while preserving the raw expression.
6. Conflict and correction handling plus a derived current-location read model.
7. Human review, versioned reprocessing, quality monitoring, and drift detection.
8. Add other languages through explicit language-specific datasets, prompts, evaluation
   baselines, and release criteria; do not assume English quality transfers automatically.
