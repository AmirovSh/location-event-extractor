# Location Event Extractor

Backend MVP that converts one already-parsed chat message into auditable, typed person-location
events. The LLM produces typed event candidates; deterministic code validates candidate
completeness, typed-field consistency, and evidence provenance before PostgreSQL persistence.

The current extraction contract, test suite, and evaluation dataset are English-only.
Reference and polarity decisions are represented as typed semantic fields; validation does not
use word lists or phrase-matching rules. Other languages are a planned, separately evaluated
extension.

Detailed technical rules and decisions are consolidated in [docs/DESIGN.md](docs/DESIGN.md).
Current progress and planned extensions are tracked in [docs/ROADMAP.md](docs/ROADMAP.md).

## What processing produces

For every accepted statement, the service records an auditable location event and its supporting
metadata:

- the person and location exactly as mentioned in the message;
- a typed relation such as `AT`, `TO`, `FROM`, `ARRIVED`, or `LEFT`;
- certainty, polarity, the raw time expression, and the source timestamp;
- the exact evidence span that supports the event;
- provenance linking the event to its source message and extraction run.

Person and location mentions are then resolved independently. When the available evidence is
sufficient, the result includes their canonical entity IDs. When it is not, the result explicitly
remains `AMBIGUOUS` or `UNRESOLVED`; the service does not invent an identity. The original literal
mentions are preserved even after successful resolution.

| Processing result | Example |
|---|---|
| Source statement | `John S. is at the downtown branch.` |
| Extracted event | person `John S.`, relation `AT`, location `the downtown branch` |
| Semantic details | asserted, positive, with an evidence span and source time |
| Resolution | person and location each receive a canonical ID only when justified |
| Stored audit trail | source hash, extraction run, event, mentions, and resolution decisions |

## How it works

1. The LLM converts the current English message into typed event candidates.
2. Deterministic validation checks required fields, enum consistency, and evidence provenance.
3. Accepted events and rejected candidates are persisted separately in PostgreSQL.
4. Entity resolution searches only eligible person or location records within the configured
   context. Models may rank or compare candidates, but deterministic code owns final database IDs.
5. High-confidence semantic matches may create a narrowly scoped alias with full provenance, making
   later mentions resolvable without discarding the original wording.

Processing is idempotent for the same source message and extractor/schema version. Provider failure
does not force an identity choice, and resolution decisions can be superseded without rewriting the
original event. Detailed workflows, data relationships, and resolution rules are documented in
[docs/DESIGN.md](docs/DESIGN.md); evaluated capabilities and planned work are tracked in
[docs/ROADMAP.md](docs/ROADMAP.md).

## Using events to track a person's location

The persisted events provide the input for a current-location or movement-history view. A consumer
can group events by the resolved canonical person, order them by source time, and apply domain rules
to their typed meaning:

- positive, asserted `AT` or completed `ARRIVED` events can establish presence;
- `LEFT` events can end previously established presence;
- `TO`, planned, or possible events describe movement or intent rather than confirmed presence;
- negated events are negative evidence and must not establish a location;
- ambiguous or unresolved identities remain visible for review but must not be silently merged.

Every derived location should retain links to the underlying events and evidence so that it can be
explained or recomputed. The project currently provides extraction, persistence, and entity
resolution; a dedicated current-location projection with conflict and recency policies is planned,
not yet part of the MVP.

## Local setup

Requires Python 3.11+ (3.12 recommended), Docker, and an OpenAI API key for real extraction.

```bash
python -m venv .venv
# PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
docker compose up -d postgres
$env:LOCATION_DATABASE_URL="postgresql+psycopg://location:location@localhost:55432/location"
$env:LOCATION_OPENAI_API_KEY="..."
python -m alembic upgrade head
uvicorn location_extractor.api:app --reload
```

The API is `POST /v1/location-events/extract`; health is `GET /health`.

```bash
curl -X POST http://localhost:8000/v1/location-events/extract \
  -H "content-type: application/json" \
  -d '{"conversation_id":"conv-42","message_id":"msg-1001","author_id":"user-5","sent_at":"2026-08-31T10:15:00+05:00","text":"John is in London now"}'
```

The response contains one outcome per candidate, with its rejection reason or persisted event
ID. `replayed: true` means that message/extractor/schema version was already processed. Reusing
a message identity with different text returns HTTP 409.

## End-to-end example

For the request above, the adapter sends the current message to the model as:

```text
message_id: msg-1001
sent_at: 2026-08-31T10:15:00+05:00
text: John is in London now
```

The versioned system prompt and the Pydantic `ExtractionResult` schema are supplied separately.
A valid structured model response is:

```json
{
  "events": [
    {
      "person_mention": "John",
      "person_reference": "EXPLICIT",
      "location_mention": "London",
      "location_reference": "EXPLICIT",
      "relation": "AT",
      "certainty": "ASSERTED",
      "polarity": "POSITIVE",
      "location_type": "CITY",
      "temporal_raw": "now",
      "evidence_text": "John is in London now",
      "evidence_start": 0,
      "evidence_end": 21,
      "ambiguous": false,
      "ambiguity_reason": null
    }
  ]
}
```

After deterministic validation, one transaction creates:

| Table | Relevant values |
|---|---|
| `source_messages` | `msg-1001`, `conv-42`, author and timestamp, SHA-256 text hash |
| `extraction_runs` | source FK, extractor/schema versions, provider/model, `PERSISTED`, latency |
| `location_events` | run/source FKs plus the accepted candidate fields and evidence span |

The complete message text is not stored. If validation rejects a candidate, its typed fields and
reason go to `extraction_rejections` instead of `location_events`. A repeated request with the
same message and extractor/schema versions returns the existing run without another model call.

## Configuration

Versioned non-secret defaults live in
`src/location_extractor/config_files/application.toml`; LLM instructions and their version live
in `src/location_extractor/config_files/prompts.toml`. Environment variables override application
defaults and remain the correct place for deployment credentials.

All variables use the `LOCATION_` prefix:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://location:location@localhost:55432/location` | SQLAlchemy database URL |
| `EXTRACTOR_BACKEND` | `openai` | `openai` or test-only `fake` |
| `EXTRACTOR_VERSION` | `mvp-1` | Idempotency/reprocessing version |
| `SCHEMA_VERSION` | `1.1` | Structured contract version |
| `PROMPT_VERSION` | `mvp-5` | Provider instruction version |
| `OPENAI_API_KEY` | unset | Required for the OpenAI backend |
| `OPENAI_BASE_URL` | OpenAI default | OpenAI-compatible base URL used by the configured API mode |
| `ALLOW_INSECURE_HTTP` | `false` | Explicit opt-in for trusted-network HTTP endpoints |
| `OPENAI_TRUST_ENV` | `true` | Honor HTTP proxy environment variables |
| `OPENAI_API_MODE` | `responses` | `responses` or compatible `chat_completions` |
| `OPENAI_MAX_OUTPUT_TOKENS` | `4096` | Bounded output/reasoning budget for chat compatibility mode |
| `OPENAI_ENABLE_THINKING` | unset | Qwen-compatible thinking toggle for chat mode |
| `OPENAI_TEMPERATURE` | `0` | Deterministic extraction sampling temperature |
| `OPENAI_MODEL` | `gpt-5-mini` | Responses API model |
| `OPENAI_TIMEOUT_SECONDS` | `20` | Per-request timeout |
| `OPENAI_MAX_RETRIES` | `2` | Bounded SDK retries |
| `EMBEDDING_API_KEY` | falls back to `OPENAI_API_KEY` | Optional separate embedding credential |
| `EMBEDDING_BASE_URL` | falls back to `OPENAI_BASE_URL` | Optional separate embedding endpoint |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI-compatible embedding model |
| `EMBEDDING_DIMENSIONS` | unset | Optional provider-supported output dimension |
| `EMBEDDING_TIMEOUT_SECONDS` | `20` | Per-request embedding timeout |
| `EMBEDDING_MAX_RETRIES` | `2` | Bounded embedding retries |
| `EMBEDDING_TOP_K` | `3` | Number of semantic candidates retained |
| `EMBEDDING_CORPUS_LIMIT` | `1000` | Maximum same-scope entities embedded per query |
| `RERANKER_API_KEY` | falls back to embedding/OpenAI key | Optional reranker credential |
| `RERANKER_BASE_URL` | falls back to embedding/OpenAI URL | Common `POST /rerank` endpoint base URL |
| `RERANKER_MODEL` | `bge-reranker-v2-m3` | OpenAI-compatible reranker model |
| `RERANKER_TIMEOUT_SECONDS` | `20` | Per-request reranker timeout |
| `RERANKER_MAX_RETRIES` | `2` | Bounded reranker retries for transient failures |
| `RERANKER_TOP_N` | `3` | Number of embedding candidates retained after reranking |
| `RESOLUTION_ENABLED` | `true` | Resolve persisted person/location mentions |
| `RESOLUTION_VERIFIER_MODEL` | `gpt-5-mini` | Pairwise and candidate-set verifier model |
| `RESOLUTION_VERIFIER_CONCURRENCY` | `2` | Global bound for concurrent verifier calls |

Docker Compose exposes PostgreSQL on host port `55432` by default to avoid common conflicts
with a locally installed PostgreSQL. Override it with `LOCATION_POSTGRES_PORT` if needed.

The service also reads `.env.runtime`. For compatibility, `OPENAI_API_KEY` and
`SEMANTIC_GRAPH_LLM_BASE_URL` map to the OpenAI adapter. A trusted-network HTTP runtime requires
`LOCATION_ALLOW_INSECURE_HTTP=true`. Set `LOCATION_OPENAI_TRUST_ENV=false` when the corporate
endpoint must bypass the process proxy.

Extraction sends only the current message. Resolution may additionally send bounded context from
that message and eligible ID-free canonical names and aliases; it sends neither database identifiers
nor previous full messages. Logs omit message text and plaintext person-location pairs. The database
stores message metadata and SHA-256 rather than full source text; bounded evidence substrings are
retained for provenance.

## Quality gates

```bash
ruff format --check .
ruff check .
mypy src
pytest -m "not integration"
```

PostgreSQL integration test (after migrations):

```bash
$env:TEST_DATABASE_URL=$env:LOCATION_DATABASE_URL
pytest -m integration
```

No live model call is part of CI. The deterministic scorer and English dataset are covered by
ordinary tests. Semantic fixtures are in `tests/fixtures/extraction_cases.json`.

Run the bounded live LLM smoke set with explicitly configured runtime access:

```bash
$env:LOCATION_ALLOW_INSECURE_HTTP="true"  # trusted corporate HTTP only
$env:LOCATION_OPENAI_TRUST_ENV="false"    # bypass a blocking process proxy if required
$env:LOCATION_OPENAI_MODEL="deepseek-v4-flash"  # verified corporate runtime model
$env:LOCATION_OPENAI_API_MODE="chat_completions"
$env:LOCATION_OPENAI_ENABLE_THINKING="false"
python scripts/run_live_eval.py --case-retries 1 --concurrency 2
```

The command prints aggregate precision/recall/F1 and field accuracies, then writes a detailed
ignored report to `evaluation-results/live-eval.json`. Use `--dataset` and `--output` to override
either path. Provider failures and candidates rejected by deterministic validation are reported
separately. Cases with provider failures are excluded from semantic metric denominators rather
than being counted as abstentions. `--concurrency` bounds independent single-message provider
calls; report order still follows dataset order. The report includes per-case latency and aggregate
wall time, average, p50, p95, maximum, throughput, and retry counts.
The bundled 64-case dataset assigns every message one primary regression category: presence,
movement, modality, attribution, multiple events, travel context, unresolved references,
hypotheticals, or non-physical mentions. The JSON report includes metrics for each category so a
strong aggregate score cannot hide a weak semantic area.
Use repeatable `--category`, for example `--category hypothetical --category travel_context`, to
run a focused prompt-development check before paying the cost of another complete baseline.
Per-case latency is end-to-end from task scheduling through semaphore waiting, retries, provider
work, and validation; it therefore represents observed runner latency rather than provider-only
service time.

## Semantics and limits

`AT`, `TO`, `FROM`, `LEFT`, `ARRIVED`, and `NEAR` stay distinct. Negated, probable, possible,
and planned events may be retained, but this MVP does not build derived current-location state.
Pronoun resolution, deictic locations, dialogue context, geocoding, relative-time normalization,
conflict reconciliation, and streaming remain outside the extraction endpoint. Scoped resolution
of explicit English person/location mentions is active when configured. Conservative scoped alias
promotion is active; scope widening and the experimental reranker remain disabled.
