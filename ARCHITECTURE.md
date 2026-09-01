# Architecture

## Architectural style

Для MVP использовать **modular monolith**. Границы модулей должны быть достаточно явными, чтобы отдельные части можно было масштабировать или заменить позже, но без стоимости ранних микросервисов.

## Core principle

LLM — semantic parser, а не источник бизнес-истины.

```text
Parsed Message
    |
    v
[Candidate Detector] ---- optional / cheap
    |
    v
[LLM Extractor]
    |
    v
LocationEventCandidate
    |
    v
[Deterministic Validator]
    |
    +---- reject / ambiguous ----> audit/metrics
    |
    v
[Entity Resolution Boundary]
    |
    v
[Persistence Mapper]
    |
    v
LocationEvent + Provenance
    |
    v
PostgreSQL
```

## Recommended module boundaries

```text
src/
  api/
    routes/
    schemas/
  application/
    services/
    ports/
  domain/
    models/
    enums/
    rules/
  infrastructure/
    llm/
    nlp/
    db/
    observability/
  config/
tests/
  unit/
  integration/
  fixtures/
  evals/
```

Names may follow existing repository conventions.

## Components

### 1. Message boundary

Incoming message is already parsed by an upstream system. This service must not parse Telegram/Slack/WhatsApp payloads directly in MVP.

Required fields:

- `conversation_id`
- `message_id`
- `sent_at`
- `text`

Optional metadata:

- `author_id`
- source/platform
- locale/language

### 2. Candidate Detector

Purpose: reduce expensive LLM calls, not make the final semantic decision.

Implement behind an interface so strategies can be swapped:

- `AlwaysPassDetector` — preferred default for correctness during early MVP/evals;
- optional `StanzaCandidateDetector` — NER/POS/dependency features;
- future lightweight classifier.

Stanza result must never itself create `LocationEvent`.

### 3. LLM Extractor

Input:

- one message;
- message timestamp/timezone metadata;
- extraction schema version.

Output:

- one or more `LocationEventCandidate` objects if needed by chosen contract;
- explicit abstention supported.

Even in MVP, allowing `events: [] | [candidate, ...]` is useful because one message may contain multiple explicit location events. If implementation simplicity favors one candidate, document the limitation and do not pretend the second event was handled.

### 4. Candidate Validator

Pure/deterministic where possible.

Checks:

- required mentions exist;
- evidence belongs to source text or has valid offsets;
- enum values valid;
- ambiguity rules;
- unsupported reference-only mentions (`он`, `там`) rejected in MVP;
- semantic constraints such as negation/planning classification are explicit.

### 5. Entity resolution boundary

MVP may persist mentions without canonical person/location entity IDs or may create minimal mention entities. Do not let LLM invent canonical IDs.

Future resolution flow:

```text
mention
  -> candidate lookup
  -> deterministic/business filters
  -> ranker / LLM resolver
  -> canonical entity | ambiguous | unknown
```

### 6. Persistence

Store immutable-ish events and provenance. Corrections should prefer new versions/superseding relationships over destructive overwrites.

Derived `current_person_location` is not required for MVP. If implemented, it must be a view/read-model based on trustworthy event types, not the direct output of extractor.

## Data flow example

Message:

`Петр приехал в Астану сегодня утром.`

1. Detector: relevant.
2. Extractor candidate:
   - person=`Петр`
   - location=`Астану`
   - relation=`ARRIVED`
   - certainty=`ASSERTED`
   - temporal_raw=`сегодня утром`
3. Validator accepts.
4. No canonical resolver yet -> mentions stored as extracted.
5. Repository creates event + source link.
6. API returns persisted event id.

## Error model

Distinguish at least:

- input validation error;
- not relevant / no event;
- ambiguous extraction;
- extractor provider error;
- schema violation from provider;
- validation rejection;
- database error;
- duplicate/idempotent replay.

Do not turn all outcomes into HTTP 500.

## Versioning

Persist:

- `extractor_version`
- `schema_version`
- model/provider metadata where allowed
- prompt/instruction version identifier

This enables reprocessing and eval comparisons without losing provenance.

## Future extensions

The architecture must allow, in order:

1. location normalization;
2. person registry/entity resolution;
3. person coreference across message history;
4. location coreference;
5. temporal normalization and intervals;
6. event conflict resolution;
7. derived current-location read model;
8. confidence-based human review.
