# ADR-001: Event-centric location model

## Status

Accepted.

## Context

Messages can express current presence, arrival, departure, direction, negation, plans and corrections. A single mutable `current_location` column loses this information and makes later temporal/context reasoning difficult to audit.

## Decision

Persist `LocationEvent` records with source provenance. Treat current location as a future derived read model over selected trustworthy events.

## Consequences

Positive:

- complete history;
- reprocessing and comparison between extractor versions;
- explicit handling of movement/uncertainty;
- easier conflict reconciliation.

Costs:

- requires read-model logic for convenient current state;
- more rows and event semantics to maintain.
