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
- opt-in live LLM smoke command.

Not active in the current workflow:

- Stanza/NLP pre-filter (`AlwaysPassDetector` is used);
- live-model quality metrics and baseline comparison.

## Next

1. Build an evaluation harness for precision, recall, relation/certainty accuracy, exact match,
   false positives, and abstention quality.
2. Expand the anonymized English fixture set with noisy chat, attribution, multi-event, and
   contrastive negative cases.
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
