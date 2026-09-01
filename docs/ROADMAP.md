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
  `deepseek-v4-flash` baseline;
- bounded live-evaluation concurrency with stable ordering and latency/retry statistics.
- a categorized 64-case English regression dataset with per-category quality metrics.

Not active in the current workflow:

- Stanza/NLP pre-filter (`AlwaysPassDetector` is used).

Latest full local baseline (2026-09-01, prompt `mvp-5`, schema `1.1`, 4096 output tokens): 56 of 64
cases received a provider response, event-detection F1 was 0.985, whole-event F1 was 0.937, and
abstention accuracy was 0.957. Multiple events, travel context, and hypothetical categories scored
1.0 in both a focused 18-case run and the full run. The full run had eight API timeouts and one
non-physical ownership false positive; provider reliability and model variability remain separate
from semantic scoring. This synthetic dataset is a regression baseline, not a production-readiness
claim.

A bounded-concurrency run with two request slots completed all 24 cases in 297 seconds with no
provider failures, four retried cases, event-detection F1 of 0.968, and whole-event F1 of 0.941.
One ticket-purchase negative case became a false positive on its retry, confirming that repeated
live runs are required to characterize model variability.

Concurrency trials on the same endpoint kept `2` as the default: `3` slots reduced wall time to
245 seconds but lost two cases to API timeouts, while `4` slots finished in 182 seconds but lost
three cases. For evaluation, complete coverage is more valuable than the additional throughput;
higher limits remain available as an explicit CLI override for other provider deployments.

## Next

1. Add anonymized production-like edge cases to the categorized English regression dataset as
   they are discovered.
2. Consider a Stanza or lightweight detector only if measured recall is safe and LLM cost/latency
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
