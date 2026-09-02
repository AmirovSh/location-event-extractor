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
- typed contextual entity-resolution contracts for people and locations;
- scoped canonical entities, aliases, mentions, and reversible decisions in PostgreSQL;
- deterministic exact-alias candidate retrieval with tenant isolation and an English resolution
  fixture baseline.
- a reproducible 24-case deterministic resolution evaluator with retrieval, ranking, decision,
  coverage, ambiguity, and isolation metrics.
- an OpenAI-compatible `MentionEmbedder`, exact-first hybrid retrieval, fake-based CI coverage, and
  an opt-in `bge-m3` retrieval baseline without vector persistence.
- a provider-independent reranker, bounded `POST /rerank` adapter, score-margin diagnostics, and
  repeatable live comparison against `bge-reranker-v2-m3`.
- typed pairwise semantic verification, bounded candidate-set adjudication, deterministic ID
  mapping, and a blind synthetic functional evaluation command.
- an autonomous extraction-to-PostgreSQL vertical slice with scoped person/location resolution,
  durable decisions, and idempotent replay.
- controlled, scoped alias promotion from high-confidence verified decisions with durable mention
  and decision provenance.

Not active in the current workflow:

- Stanza/NLP pre-filter (`AlwaysPassDetector` is used).

Latest full local baseline (2026-09-01, prompt `mvp-5`, schema `1.1`, 4096 output tokens): 56 of 64
cases received a provider response, event-detection F1 was 0.985, whole-event F1 was 0.937, and
abstention accuracy was 0.957. Multiple events, travel context, and hypothetical categories scored
1.0 in both a focused 18-case run and the full run. The full run had eight API timeouts and one
non-physical ownership false positive; provider reliability and model variability remain separate
from semantic scoring. This synthetic dataset is a regression baseline, not a production-readiness
claim.

Deterministic entity-resolution baseline (2026-09-02, `scoped-exact-alias-v1`, 16 cases):
candidate recall@1/3 and top-1 accuracy were 0.636, candidate-set recall was 0.714, outcome accuracy
was 0.750, and automatic-resolution coverage was 0.438. Resolved precision, ambiguity accuracy,
and unresolved accuracy were 1.0; tenant and entity-type leakage counts were zero. Four semantic
challenge cases remain unresolved by design and define the target for embedding retrieval.

Embedding retrieval baseline (2026-09-02, `bge-m3`, exact-first, top-K 3): candidate recall@1/3,
candidate-set recall, and top-1 accuracy reached 1.0 on the same 16 cases. Resolved precision,
ambiguity accuracy, and unresolved accuracy remained 1.0 with zero tenant/type leakage. Outcome
accuracy stayed 0.750 and automatic coverage stayed 0.438 by design: embedding-only candidates are
retrieved but cannot yet create an automatic resolution decision.

Reranker challenge evaluation (2026-09-02, 24 cases, three repeated runs): `bge-m3` kept top-1
accuracy 1.0 while `bge-reranker-v2-m3` consistently scored 0.941; both kept recall@3 1.0 and zero
tenant/type leakage. Reranker maximum score on an unresolved case was approximately 0.976, so an
absolute score threshold does not separate supported from unsupported mentions. The reranker is not
eligible for automatic linking on current evidence.

Synthetic verifier proof (2026-09-02, 24 cases): `deepseek-v4-flash` pairwise verification plus
candidate-set adjudication and deterministic aggregation reached outcome accuracy 1.0, resolved
precision 1.0, ambiguity/unresolved accuracy 1.0, and zero tenant/type leakage in the final blind
run. This demonstrates feasibility on prepared synthetic messages, not production readiness or
cross-run stability.

Expanded vertical-slice run (2026-09-02, 10 messages, 11 expected events): all ten events that
reached the pipeline matched expected person IDs, location IDs, and resolution outcomes, including
ambiguity, partial resolution, multiple events, and tenant isolation. One extraction request failed
at the provider boundary, producing reported all-event accuracy of 0.909 and one provider failure;
the batch continued. PostgreSQL contained 12 automatically promoted aliases, all with mention and
decision provenance.

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
2. Continue expanding the autonomous vertical-slice fixture beyond its current ambiguity, multiple
   events, provider failure, partial-resolution, and tenant-isolation cases.
3. Add more independently sourced or anonymized production-like resolution cases before making any
   non-synthetic release claim.
4. Define an evidence-based deterministic automatic-link policy only if a broader evaluation
   demonstrates safe precision and ambiguity separation.
5. Define production release criteria for the integrated resolution behavior; current evidence is
   synthetic and proves architecture/functionality rather than production readiness.
6. Consider a Stanza or lightweight detector only if measured recall is safe and LLM cost/latency
   makes filtering worthwhile.

## Post-MVP

1. Canonical location hierarchy and reviewed widening of promoted alias scopes.
2. Bounded person coreference over dialogue context.
3. Location/deictic coreference over dialogue context.
4. Relative-time normalization while preserving the raw expression.
5. Conflict and correction handling plus a derived current-location read model.
6. Human review, versioned reprocessing, quality monitoring, and drift detection.
7. Add other languages through explicit language-specific datasets, prompts, evaluation
   baselines, and release criteria; do not assume English quality transfers automatically.
