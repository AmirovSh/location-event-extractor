# AGENTS.md

## Mission

Build a reliable service that converts chat messages into verifiable structured events about a
person's location. Priorities: correctness, traceability, extensibility, and safe handling of
sensitive data.

## Read first

Before changing code, read these files in order:

1. `docs/DESIGN.md`
2. `docs/ROADMAP.md`
3. `README.md`

## Engineering rules

- Never allow the LLM to modify business state directly or select final database identifiers.
- First create a typed candidate, then validate and normalize it with deterministic code, and only
  then persist it.
- Every persisted fact must retain provenance to the source message and evidence span.
- The system must be able to return `unknown` or `ambiguous`; never force a guess.
- MVP: one message, explicit person, explicit location. Do not implement full dialogue coreference
  before the basic version.
- Use Stanza only behind an interface. It must not be tightly coupled to domain logic.
- Avoid premature microservices. Use a modular monolith with clear interfaces for the MVP.
- Do not add a vector database, graph database, Kafka, or a separate orchestration framework without
  demonstrated need.
- Every new dependency must have a specific purpose and minimal blast radius.
- Change the database schema only through migrations.
- Public API models must not be ORM models.

## Quality gates

Before completing changes:

- formatter and linter pass;
- type checks pass when configured;
- unit tests pass;
- integration tests pass;
- tests cover new extraction branches;
- new LLM schema fields have backward-compatible handling or explicit versioning;
- logs contain neither secrets nor full message text by default;
- inspect `git diff` for accidental changes.

## Preferred implementation style

- Small functions and explicit types.
- Dependency inversion for the LLM provider, repository, NLP pre-filter, and clock.
- Pydantic models at boundaries and for contracts.
- Domain enums instead of unconstrained strings.
- Use UTC internally; preserve the original timezone and raw time expression separately.
- Idempotency by `source_message_id + extractor_version` or an equivalent key.

## Tests

Every bug fix must add a regression test. Separate LLM-dependent logic into:

- deterministic unit tests without network access;
- provider adapter tests with mocks or fakes;
- optional live evaluations that are not part of required CI.

## Stop conditions

Do not expand scope beyond the current MVP and roadmap boundaries documented in `docs/DESIGN.md`
and `docs/ROADMAP.md`. If an ambiguity is discovered, choose the smallest compatible solution and
document any architecturally significant assumption in `docs/DESIGN.md`.
