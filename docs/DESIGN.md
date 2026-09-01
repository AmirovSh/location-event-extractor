# Design

This document is the compact technical specification for the MVP. `TASK.md` defines the
product scope; `README.md` explains operation and local development.

## Architecture

The service is a modular monolith with dependency-inverted boundaries:

```text
ParsedMessage
  -> LocationCandidateDetector
  -> LocationEventExtractor
  -> LocationEventCandidate
  -> CandidateValidator
  -> LocationEventRepository
  -> PostgreSQL
```

The default detector is `AlwaysPassDetector`. Stanza is not currently used; a future detector
may pre-filter messages only after its recall has been measured. Detector output must never
create domain events.

The LLM is a semantic parser, not a source of business truth. It returns typed candidates and
cannot select database identifiers or persist state. The application validates every candidate
deterministically before persistence.

## Domain contract

`LocationEventCandidate` describes untrusted model output:

- literal `person_mention` and `location_mention`;
- typed explicitness: `EXPLICIT`, `REFERENCE`, or `UNKNOWN`;
- relation: `AT`, `TO`, `FROM`, `LEFT`, `ARRIVED`, `NEAR`, or `UNKNOWN`;
- certainty: `ASSERTED`, `PROBABLE`, `POSSIBLE`, `NEGATED`, `PLANNED`, or `UNKNOWN`;
- polarity: `POSITIVE`, `NEGATIVE`, or `UNKNOWN`;
- optional location type and raw temporal expression;
- evidence text and character offsets;
- ambiguity flag and bounded reason.

An accepted `LocationEvent` is a sourced assertion, movement, plan, uncertainty, or negation.
It is not a person's derived current location. That state may later be computed from trustworthy
events using explicit business rules.

## Extraction rules

The MVP extraction contract and all automated evaluation data are English-only. Support for
additional languages requires separate datasets and quality baselines and is tracked in the
roadmap. Extraction operates on one message without dialogue history.

- Extract physical person-location presence or movement only.
- Preserve literal mentions and evidence; do not canonicalize or geocode.
- Keep presence, direction, arrival, and departure distinct.
- Preserve assertion, uncertainty, negation, and future plans.
- Return multiple independent events when present.
- Abstain when the person or location is unresolved or the text only expresses preference,
  discussion, ownership, imagination, or a conditional situation.
- Do not expose chain-of-thought. Structured output is enforced by the Pydantic/JSON schema.

Examples:

| Message | Result |
|---|---|
| `John is in London.` | `John / London / AT / ASSERTED` |
| `Peter arrived in Astana.` | `ARRIVED / ASSERTED` |
| `Anna is going to the airport.` | `TO`; not confirmed `AT` |
| `John is not in London.` | `AT / NEGATED` |
| `John may be in London.` | `AT / POSSIBLE` |
| `John will travel to London tomorrow.` | `TO / PLANNED`, preserve `tomorrow` |
| `John said that Mary is in Boston.` | subject is `Mary` |
| `John likes London.` | no event |
| `He is in London.` | reject/abstain: unresolved person |
| `John is there.` | reject/abstain: unresolved location |

## Deterministic validation

A candidate is persistable only when:

- person, location, and evidence are present;
- person and location are typed as explicit;
- evidence occurs in the source and contains both literal mentions;
- offsets match, or can be repaired from one unique evidence occurrence;
- relation is known and the candidate is not ambiguous;
- polarity and certainty are consistent.

Expected rejections are returned as typed reasons, not generic exceptions. Validation relies on
typed semantic fields rather than language-specific word lists or regular expressions.

## Persistence and provenance

PostgreSQL stores:

- `source_messages`: external identity, metadata, timestamp, and text hash;
- `extraction_runs`: provider/model/version, status, latency, and the idempotency record;
- `location_events`: accepted event fields and evidence;
- `extraction_rejections`: rejected candidates and typed reasons.

The idempotency key is the source message plus extractor and schema versions. Reprocessing with a
new version remains possible. Schema changes use Alembic migrations. ORM models do not cross the
public API boundary.

## Security and operations

Location data is sensitive. Store only required fields, keep secrets in environment variables,
and do not log complete messages or plaintext person-location pairs. Logs use identifiers, hashes,
lengths, typed outcomes, and latency. Only the current message is sent to the configured provider.

HTTPS is the default provider transport. Plain HTTP requires explicit configuration and is only
intended for a trusted internal network accepted by the deployment owner. Production deployment
still needs authentication, authorization, retention, deletion, and tenant-boundary policies.

## Testing policy

Normal CI is deterministic and does not call a live model:

- unit tests cover contracts, validation, orchestration, adapter mapping, and SQLite repository
  behavior;
- API tests cover request validation and response outcomes;
- PostgreSQL integration tests cover migrations, persistence, and idempotency;
- live model evaluations are opt-in and report provider reliability separately from semantic
  quality.

Every extraction change should add a positive case and a contrastive negative case. Important
regression dimensions are subject attribution, false-positive locations, modality/negation,
movement versus presence, missing context, and evidence provenance.

## Accepted decisions

1. Store immutable sourced events; derive current location later.
2. Treat LLM output as an untrusted candidate.
3. Keep a modular monolith until scaling evidence justifies another deployment model.
4. Keep Stanza optional and recall-oriented.
5. Preserve raw temporal text if normalization is added.
6. Prefer explicit abstention over fabricated resolution.
7. Use typed semantics instead of lexical validation rules.
