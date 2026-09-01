# Database design

## Goals

- preserve provenance;
- keep events auditable;
- allow reprocessing with new extractor versions;
- avoid destructive overwrite of source facts;
- support future entity resolution and temporal intervals.

## Tables

### `source_messages`

Suggested columns:

```text
id                 UUID PK
external_message_id TEXT NOT NULL
conversation_id     TEXT NOT NULL
author_id           TEXT NULL
sent_at             TIMESTAMPTZ NOT NULL
text_ciphertext      TEXT/BYTEA NULL   # only if policy permits storing source text
text_hash            TEXT NOT NULL
created_at           TIMESTAMPTZ NOT NULL
UNIQUE(conversation_id, external_message_id)
```

If the upstream source remains authoritative, storing full message text locally is optional. At minimum preserve message identifiers and evidence necessary for audit according to privacy policy.

### `location_events`

```text
id                  UUID PK
source_message_id   UUID NOT NULL FK -> source_messages.id
person_id            UUID NULL
person_mention       TEXT NOT NULL
location_id          UUID NULL
location_mention     TEXT NOT NULL
relation             TEXT/ENUM NOT NULL
certainty            TEXT/ENUM NOT NULL
location_type        TEXT/ENUM NOT NULL
temporal_raw         TEXT NULL
valid_from           TIMESTAMPTZ NULL
valid_to             TIMESTAMPTZ NULL
evidence_text        TEXT NOT NULL
evidence_start       INT NULL
evidence_end         INT NULL
ambiguous            BOOLEAN NOT NULL DEFAULT FALSE
extractor_version    TEXT NOT NULL
extractor_provider   TEXT NULL
extractor_model      TEXT NULL
schema_version       TEXT NOT NULL
created_at           TIMESTAMPTZ NOT NULL
```

### `extraction_runs`

Recommended for idempotency/observability:

```text
id                  UUID PK
source_message_id   UUID NOT NULL
extractor_version   TEXT NOT NULL
schema_version      TEXT NOT NULL
status              TEXT NOT NULL
rejection_reason    TEXT NULL
latency_ms           INT NULL
created_at           TIMESTAMPTZ NOT NULL
UNIQUE(source_message_id, extractor_version, schema_version)
```

This unique constraint prevents accidental duplicate processing for the same extraction version. Reprocessing with a newer version remains possible.

## Future tables

### `persons`

Canonical entity registry.

### `person_aliases`

Aliases/mentions linked to a person with provenance/confidence.

### `locations`

Canonical hierarchy-enabled locations.

### `location_aliases`

Raw names and alternate spellings.

### `event_supersessions`

Tracks that one derived interpretation supersedes another without deleting history.

## Indexes

MVP useful indexes:

- `source_messages(conversation_id, external_message_id)` unique;
- `location_events(source_message_id)`;
- `location_events(person_id, created_at)` when person ids arrive;
- `location_events(location_id, created_at)` when location ids arrive;
- `extraction_runs(status, created_at)` for operations.

## Derived current state

Do not store `person.current_location_id` as the only source of truth.

Future read model can be a materialized view/table, rebuilt from accepted events. Rules must explicitly define which combinations of relation/certainty count as confirmed presence.

## Migrations

Use Alembic or the existing project migration framework. CI integration test should apply all migrations to an empty PostgreSQL database.
