# ADR-002: LLM produces candidates, not business state

## Status

Accepted.

## Context

An LLM can extract semantic structure well, but its output can be incomplete, ambiguous, inconsistent across versions, or semantically wrong despite matching JSON schema.

## Decision

LLM returns only typed `LocationEventCandidate` records. Deterministic application/domain code validates them, resolves allowed identifiers, applies idempotency, and persists accepted `LocationEvent` records.

## Consequences

Positive:

- prevents invented DB ids and direct side effects;
- makes pipeline testable without provider calls;
- enables validation and review thresholds;
- isolates provider changes.

Costs:

- additional mapping/validation code;
- some rules are duplicated between prompt semantics and deterministic checks by design.
