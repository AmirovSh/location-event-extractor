# Architecture decisions summary

## D1 — Event-centric storage

Store sourced `LocationEvent` records instead of treating `person.current_location` as the source of truth.

Reason: supports history, corrections, movement, uncertainty, temporal intervals, reprocessing and audits.

See `docs/adr/ADR-001-event-centric-model.md`.

## D2 — LLM output is a candidate

LLM may interpret semantics, but cannot directly write domain state or choose canonical DB IDs.

Reason: schema correctness is not business correctness; deterministic validation and resolution are required.

See `docs/adr/ADR-002-llm-candidate-boundary.md`.

## D3 — Modular monolith first

MVP remains one deployable service with explicit internal interfaces.

Reason: complexity is semantic, not throughput/distributed-systems complexity yet.

## D4 — Stanza is optional

Stanza may be used as a recall-oriented pre-filter/feature provider after baseline LLM quality is measured.

Reason: noun/NER detection alone does not reliably determine person-location semantics and can create unrecoverable false negatives.

## D5 — Raw + normalized time

Future temporal normalization must preserve both original expression and normalized interval.

Reason: normalization algorithms change; raw evidence is necessary for reprocessing/audit.

## D6 — Explicit abstention

Unknown/ambiguous resolution is a valid state.

Reason: for identity/location tracking, a wrong confident resolution is usually worse than an unresolved candidate.

## D7 — Structured semantics instead of lexical rules

Explicitness and polarity are typed candidate fields. Deterministic validation checks their
consistency and abstains on unresolved values; it does not maintain word or phrase lists.

Reason: lexical rules are language-specific, incomplete, and cannot reliably represent context.
