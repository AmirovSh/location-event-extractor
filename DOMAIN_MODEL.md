# Domain model

## Aggregate: LocationEvent

A `LocationEvent` represents a sourced assertion, observation, movement, plan, or negation connecting a person mention/entity with a location mention/entity.

It is **not** synonymous with `current_location`.

## LocationEventCandidate

Produced by semantic extraction before persistence.

Suggested fields:

```text
person_mention: str | null
person_reference: EXPLICIT | REFERENCE | UNKNOWN
location_mention: str | null
location_reference: EXPLICIT | REFERENCE | UNKNOWN
relation: LocationRelation
certainty: Certainty
polarity: POSITIVE | NEGATIVE | UNKNOWN
subject_role: str | null
location_type: LocationType | UNKNOWN
temporal_raw: str | null
evidence_text: str | null
evidence_start: int | null
evidence_end: int | null
ambiguous: bool
ambiguity_reason: str | null
notes: str | null     # optional, never required for downstream correctness
```

Avoid model-generated free-form chain-of-thought fields.

## LocationEvent

Suggested persisted fields:

```text
id: UUID
conversation_id: str
source_message_id: str
person_id: UUID | null
person_mention: str
location_id: UUID | null
location_mention: str
relation: LocationRelation
certainty: Certainty
location_type: LocationType
temporal_raw: str | null
valid_from: datetime | null
valid_to: datetime | null
evidence_text: str
evidence_start: int | null
evidence_end: int | null
extractor_version: str
schema_version: str
created_at: datetime
```

For MVP, `person_id` and `location_id` may remain null until entity resolution exists.

## LocationRelation

Recommended semantics:

- `AT` — subject is stated to be physically at/in location.
- `TO` — directed movement toward location, not proof of arrival.
- `FROM` — movement originates from location.
- `ARRIVED` — arrival at location is asserted.
- `LEFT` — departure from location is asserted.
- `NEAR` — subject is near/around location.
- `UNKNOWN` — relation could not be classified.

Do not map all movement to `AT`.

## Certainty

- `ASSERTED` — presented as fact.
- `PROBABLE` — speaker indicates likely but uncertain.
- `POSSIBLE` — possibility only.
- `NEGATED` — statement explicitly denies relation.
- `PLANNED` — future intention/plan, not current physical fact.
- `UNKNOWN` — unresolved modality.

## LocationType

MVP-friendly enum:

- `COUNTRY`
- `CITY`
- `DISTRICT`
- `STREET`
- `ADDRESS`
- `BUILDING`
- `OFFICE`
- `HOME`
- `VENUE`
- `AIRPORT`
- `STATION`
- `OTHER`
- `UNKNOWN`

Do not block persistence only because the type is unknown if the explicit location mention itself is valid.

## Provenance

Every event must point to its source message. Preserve evidence text/offsets so a reviewer can trace the event to the exact source phrase.

## Current location as a read model

Future `CurrentPersonLocation` should be computed from events using explicit business rules. For example, a likely rule set may trust recent `AT`/`ARRIVED` + `ASSERTED`, but should not treat `TO`, `PLANNED`, `NEGATED`, `POSSIBLE` as confirmed current location.

## Entity registry — future

### PersonEntity

```text
id
canonical_name
aliases[]
metadata
```

### LocationEntity

```text
id
canonical_name
type
parent_location_id
coordinates?   # only after geocoding is intentionally introduced
aliases[]
```

Entity resolution must be auditable and allowed to abstain.
