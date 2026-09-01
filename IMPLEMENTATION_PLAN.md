# Implementation plan

## Phase 0 — bootstrap

If repository is empty:

- create package structure;
- dependency management;
- settings via environment;
- FastAPI app and health endpoint;
- PostgreSQL test/dev setup (docker compose is acceptable);
- pytest configuration;
- formatter/linter/type checker consistent with chosen toolchain.

Deliverable: service starts and tests run.

## Phase 1 — domain contracts

Implement:

- `ParsedMessage`;
- `LocationEventCandidate`;
- `ExtractionResult`;
- `LocationEvent`;
- enums from `DOMAIN_MODEL.md`;
- validation result/rejection reason types.

No LLM or database logic in this step.

Deliverable: typed models + unit tests.

## Phase 2 — extraction port and fake

Implement application port/protocol `LocationEventExtractor` and deterministic fake/fixture implementation.

Create extraction pipeline application service that can run end-to-end with the fake.

Deliverable: pipeline unit tests without network.

## Phase 3 — deterministic validation

Implement rules:

- explicit person required;
- explicit location required;
- evidence required;
- unsupported pronoun/deictic-only references rejected in MVP;
- ambiguity rejected;
- enum/schema checks;
- evidence sanity check.

Return typed rejection reason; do not throw generic exceptions for expected rejects.

Deliverable: table-driven validation tests.

## Phase 4 — persistence

Implement:

- ORM models isolated in infrastructure;
- migrations;
- repository port + SQL implementation;
- source message persistence/hash strategy;
- extraction run record;
- idempotency.

Deliverable: integration tests against PostgreSQL.

## Phase 5 — API/application orchestration

Implement `POST /v1/location-events/extract`.

Flow:

1. validate request;
2. create/find source message;
3. detect candidate relevance (default pass-through);
4. call extractor;
5. validate candidates;
6. persist accepted events;
7. record run outcome;
8. return structured response.

Deliverable: API integration tests.

## Phase 6 — OpenAI adapter

Implement real provider adapter with strict structured output.

Configuration:

- API key from environment;
- model from environment;
- timeout;
- bounded retries;
- prompt version;
- schema version.

Provider failure must be translated into infrastructure/application error types.

Deliverable: adapter tests with mocked SDK transport + optional manually runnable live smoke test.

## Phase 7 — optional Stanza detector

Only after baseline correctness exists.

Implement `StanzaCandidateDetector` behind the same port. It may use NER/POS/dependencies to cheaply mark obviously irrelevant messages.

Requirements:

- feature flag to disable;
- fail-open vs fail-closed behavior explicitly documented; default should favor recall;
- benchmark false-negative rate before enabling in production;
- no domain persistence from Stanza output alone.

Deliverable: detector tests and metrics hook.

## Phase 8 — eval harness

Create fixture dataset and command to compute:

- event detection precision/recall/F1;
- person mention exact/normalized match;
- location mention exact/normalized match;
- relation accuracy;
- certainty accuracy;
- whole-event exact match;
- abstention correctness.

Live model eval should be opt-in, not required for ordinary CI.

## Post-MVP roadmap

### R1 — Location normalization

- alias/canonical location tables;
- location hierarchy;
- candidate generation + resolution;
- optional geocoder only after policy/design approval.

### R2 — Person entity registry

- canonical person entities;
- aliases;
- explicit ambiguity;
- search APIs/tools for resolver.

### R3 — Person coreference

Input becomes current message + bounded dialogue context + known person candidates. Resolve pronouns/references with abstention.

### R4 — Location coreference

Resolve `там`, `здесь`, `туда`, named venue aliases from dialogue context.

### R5 — Temporal reasoning

Preserve raw expression and add normalized intervals anchored to message time/timezone. Support `вчера`, `до среды`, `на три дня`, etc.

### R6 — Conflict resolution

Represent supersession/corrections and derive current state from reliable events.

### R7 — Review/quality operations

Confidence/ambiguity routing, human review queue, reprocessing by extractor version, drift monitoring.
