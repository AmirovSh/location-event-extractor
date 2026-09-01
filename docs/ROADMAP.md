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
- deterministic English evaluation metrics, an opt-in live evaluation command, and a first local
  `deepseek-v4-flash` baseline.

Not active in the current workflow:

- Stanza/NLP pre-filter (`AlwaysPassDetector` is used).

Latest local baseline (2026-09-01, prompt `mvp-3`, schema `1.1`, 4096 output tokens): 23 of 24
cases received a provider response, event-detection F1 was 1.0, whole-event F1 was 0.970, and
abstention accuracy was 1.0. One negative case ended with an API timeout after two attempts. This
small synthetic dataset is a regression baseline, not a production-readiness claim.

## Next

1. Expand the anonymized English fixture set as production-like edge cases are discovered.
2. Add bounded concurrency and latency statistics to live evaluation without changing ordinary CI.
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
