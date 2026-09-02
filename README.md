# Location Event Extractor

Backend MVP that converts one already-parsed chat message into auditable, typed
person-location events. The LLM only produces candidates; deterministic code validates
explicit mentions and evidence before PostgreSQL persistence.

The current extraction contract, test suite, and evaluation dataset are English-only.
Reference and polarity decisions are represented as typed semantic fields; validation does not
use word lists or phrase-matching rules. Other languages are a planned, separately evaluated
extension.

Detailed technical rules and decisions are consolidated in [docs/DESIGN.md](docs/DESIGN.md).
Current progress and planned extensions are tracked in [docs/ROADMAP.md](docs/ROADMAP.md).

## Architecture workflow

```mermaid
flowchart TB
    subgraph Configuration["1. Configuration"]
        ApplicationConfig["application.toml<br/>DB URL · model · versions · timeouts"]
        PromptConfig["prompts.toml<br/>versioned LLM instructions"]
        Environment["Environment / .env.runtime<br/>secrets · deployment overrides"]
        ApplicationConfig --> Settings["Typed Settings"]
        PromptConfig --> Settings
        Environment --> Settings
    end

    Settings --> Composition["Composition root<br/>creates dependencies"]

    subgraph Request["2. Request boundary"]
        Client["Upstream chat system"]
        Endpoint["POST /v1/location-events/extract"]
        Message["ParsedMessage"]
        Client --> Endpoint --> Message
    end

    Message --> Service

    subgraph Pipeline["3. Application pipeline"]
        Service["LocationExtractionService"]
        Idempotency{"Result for this version<br/>already exists?"}
        Detector["LocationCandidateDetector"]
        Relevance{"Message relevant?"}
        Extractor["LocationEventExtractor"]
        Candidate["LocationEventCandidate[]"]
        Validator["CandidateValidator"]
        Decision{"Candidate persistable?"}

        Service --> Idempotency
        Idempotency -- "No" --> Detector
        Detector --> Relevance
        Relevance -- "Yes" --> Extractor
        Extractor --> Candidate --> Validator --> Decision
    end

    Composition --> Service
    Composition --> Extractor

    subgraph Outcomes["4. Typed outcomes"]
        Accepted["Accepted event"]
        Rejected["Rejected candidate<br/>+ rejection reason"]
        Empty["No event"]
        Replay["Existing result"]

        Decision -- "Yes" --> Accepted
        Decision -- "No" --> Rejected
        Relevance -- "No" --> Empty
        Idempotency -- "Yes" --> Replay
    end

    Accepted --> Repository
    Rejected --> Repository
    Empty --> Repository

    subgraph Persistence["5. Persistence transaction"]
        Repository["LocationEventRepository"]
        SourceMessage["source_messages<br/>identity · metadata · text hash"]
        ExtractionRun["extraction_runs<br/>version · status · latency"]
        StoredOutcome["location_events<br/>or<br/>extraction_rejections"]

        Repository --> SourceMessage --> ExtractionRun --> StoredOutcome
    end

    Repository --> Result
    Replay --> Result

    subgraph Response["6. Response"]
        Result["ProcessResult<br/>status · outcomes · event IDs · replayed"]
        ClientResponse["HTTP response"]
        Result --> ClientResponse
    end
```

The central trust boundary is:

```text
LLM -> typed candidate -> deterministic validation -> persistence
```

| Component | Responsibility | Why it exists separately |
|---|---|---|
| `ParsedMessage` | Typed contract for one upstream message | Keeps platform-specific payloads outside the domain |
| `Settings` and TOML files | Load versioned defaults, prompts, secrets and deployment overrides | Keeps configuration out of business logic and makes prompts auditable |
| `LocationExtractionService` | Orchestrate detection, extraction, validation and persistence | Makes the use-case order explicit and independently testable |
| `LocationCandidateDetector` | Decide whether semantic extraction is needed | Allows a future recall-oriented pre-filter without coupling it to persistence |
| `LocationEventExtractor` | Provider-independent semantic extraction port | Prevents OpenAI-specific types from entering application and domain layers |
| OpenAI-compatible adapter | Call Responses or Chat Completions with structured output | Isolates provider transport, timeout, retry and schema-parsing details |
| `LocationEventCandidate` | Represent typed but untrusted model output | Prevents the LLM from directly changing business state |
| `CandidateValidator` | Check completeness, typed semantic invariants and provenance | JSON Schema validates structure, not business correctness |
| `LocationEventRepository` | Persist one transactional processing outcome | Keeps SQLAlchemy and transaction details outside the application service |
| `source_messages` | Store message identity, metadata and text hash | Provides provenance without retaining the full source message |
| `extraction_runs` | Store version, status and latency | Provides idempotency and controlled reprocessing with newer versions |
| `location_events` | Store accepted sourced assertions | Events remain the source of truth instead of a mutable current-location field |
| `extraction_rejections` | Store rejected candidates and reasons | Makes model and validation failures auditable |
| `ProcessResult` | Return accepted, rejected, empty or replayed outcomes | Keeps extraction outcome distinct from persistence outcome |

Structured logs record metadata, decisions and latency across the workflow without logging full
message text or plaintext person-location pairs.

## Contextual entity resolution foundation

The persisted extraction workflow can resolve person and location mentions without allowing a
model to mutate canonical identity:

```text
EntityMention + ResolutionScope
  -> scoped exact-alias retrieval
  -> ResolutionCandidate[]
  -> deterministic policy
  -> RESOLVED | AMBIGUOUS | UNRESOLVED
  -> reversible versioned decision
```

Tenant is a hard boundary. Source, conversation, and sender may narrow an alias; scoped aliases do
not leak into unrelated contexts. PostgreSQL stores canonical entities, aliases, mention provenance,
and append-oriented decisions. Superseding a decision deactivates the old link instead of deleting
or rewriting it. The original literal mention on `location_events` remains unchanged.

Exact scoped aliases are resolved deterministically. Otherwise the hybrid retriever ranks eligible
same-tenant candidates with embeddings and the verifier evaluates ID-free profiles; deterministic
policy alone maps a validated temporary position to a UUID. Unicode form, case, and whitespace are
normalized generically; there are no person/location word lists. The separate
English fixture at `tests/fixtures/resolution_cases.json` covers tenant isolation, ambiguity,
person/location type separation, and source/conversation/sender scoping. Embedding and reranker
models remain behind ports and no vectors are persisted. The evaluated reranker is not active.

Run the deterministic resolution baseline without network or model access:

```bash
python scripts/run_resolution_eval.py
```

The ignored detailed report is written to `evaluation-results/resolution-baseline.json`. It reports
candidate recall@1/3, candidate-set recall, top-1 and outcome accuracy, resolved precision,
automatic-resolution coverage, ambiguity/unresolved accuracy, and tenant/type leakage. The bundled
24-case dataset includes semantic challenges, same-name people, similarly named locations, and hard
negatives that exact alias lookup intentionally cannot resolve. Semantic retrieval must improve
ranking without reducing resolved precision or allowing any tenant/type leakage.

Run the opt-in OpenAI-compatible embedding comparison:

```bash
$env:LOCATION_ALLOW_INSECURE_HTTP="true"  # trusted internal HTTP only
$env:LOCATION_OPENAI_TRUST_ENV="false"
$env:LOCATION_EMBEDDING_MODEL="bge-m3"
python scripts/run_embedding_resolution_eval.py --top-k 3
```

The hybrid retriever always prefers deterministic exact aliases. Only when none match does it send
the bounded mention/context and same-scope candidate documents to the embedder. Embedding-only
candidates remain `UNRESOLVED`; this phase measures retrieval and does not enable model-driven
identity links. On the expanded 24-case fixture, `bge-m3` reached candidate recall@1/3 and top-1
accuracy of 1.0 while preserving resolved precision 1.0 and zero tenant/type leakage.

Compare embedding-only retrieval with the optional reranker:

```powershell
$env:LOCATION_ALLOW_INSECURE_HTTP="true"  # trusted internal HTTP only
$env:LOCATION_OPENAI_TRUST_ENV="false"
python scripts/run_reranker_resolution_eval.py `
  --embedding-model bge-m3 `
  --reranker-model bge-reranker-v2-m3 `
  --runs 3
```

The ignored report is written to `evaluation-results/reranker-resolution-eval.json`. Reranking is
limited to candidates already filtered by tenant, entity type, and scope. Exact aliases bypass both
models. The report includes correct-candidate score margins, unresolved-case top scores, and one
summary per repeated run. On the expanded fixture embedding top-1 remained 1.0 while reranker top-1
was consistently 0.941; recall@3 stayed 1.0 and leakage remained zero. An unresolved case received a
reranker score near 0.976, so neither reranking nor a simple score threshold is approved for
automatic linking.

Run the synthetic pairwise-verifier functional evaluation:

```powershell
$env:LOCATION_ALLOW_INSECURE_HTTP="true"
$env:LOCATION_OPENAI_TRUST_ENV="false"
$env:LOCATION_OPENAI_API_MODE="chat_completions"
$env:LOCATION_OPENAI_ENABLE_THINKING="false"
python scripts/run_resolution_verifier_eval.py `
  --embedding-model bge-m3 `
  --verifier-model deepseek-v4-flash `
  --top-k 3 `
  --concurrency 2
```

The verifier receives one mention/context and ID-free candidate profiles. Multiple pairwise
confirmations trigger comparative adjudication over temporary candidate positions; deterministic
code alone maps a validated position to an internal UUID. The report is written to
`evaluation-results/resolution-verifier-eval.json`. The final blind run on 24 prepared synthetic
cases reached outcome accuracy and resolved precision 1.0 with zero leakage. The same policy is now
available after event persistence when resolution is enabled.

Run the autonomous synthetic extraction-to-PostgreSQL slice:

```powershell
python scripts/run_vertical_slice.py
```

The five-message fixture exercises explicit person/location extraction, scoped semantic identity
resolution, abstention for an unknown person, durable provenance, and idempotent replay. It seeds
only canonical identities and aliases; extraction and non-exact linking still use the configured
providers. A repeated run reuses the stored events and active decisions without new verifier calls.

## Local setup

Requires Python 3.11+ (3.12 recommended), Docker, and an OpenAI API key for real extraction.

```bash
python -m venv .venv
# PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
docker compose up -d postgres
$env:LOCATION_DATABASE_URL="postgresql+psycopg://location:location@localhost:55432/location"
$env:LOCATION_OPENAI_API_KEY="..."
alembic upgrade head
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
| `OPENAI_BASE_URL` | OpenAI default | OpenAI-compatible Responses API base URL |
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

Only the current message is sent to the provider. Logs omit message text and plaintext
person-location pairs. The database stores message metadata and SHA-256 rather than full source
text; bounded evidence substrings are retained for provenance.

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
of explicit English person/location mentions is active when configured. Automatic alias promotion
and the experimental reranker remain disabled.
