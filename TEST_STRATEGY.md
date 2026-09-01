# Test strategy

## Principle

Most CI tests must not require an LLM API call. Separate deterministic pipeline correctness from model quality evaluation.

## Test layers

### 1. Domain unit tests

Test:

- enum semantics;
- model validation;
- persistability rules;
- certainty/relation behavior;
- evidence requirements.

### 2. Candidate validator tests

Use table-driven cases.

Minimum cases:

| Message | Expected |
|---|---|
| `Иван в Алматы.` | accept: Иван / Алматы / AT / ASSERTED |
| `Мария находится в офисе.` | accept |
| `Петр приехал в Астану.` | ARRIVED |
| `Сергей вышел из офиса.` | LEFT or FROM, documented |
| `Иван не в Алматы.` | NEGATED, not confirmed current location |
| `Наверное, Иван в Алматы.` | PROBABLE |
| `Иван может быть в Алматы.` | POSSIBLE |
| `Иван завтра поедет в Алматы.` | TO + PLANNED |
| `Мне нравится Алматы.` | no event |
| `Иван обсуждает Алматы.` | no event |
| `Он в Алматы.` | reject/abstain: explicit person missing |
| `Иван там.` | reject/abstain: explicit location missing |
| `Иван сказал, что Мария в Астане.` | subject must be Мария |
| `Если Иван будет в Алматы, позвони.` | conditional/non-asserted; do not mark confirmed AT |

### 3. Application service tests

With fake extractor and in-memory/fake repository verify:

- call order;
- accepted candidate persisted;
- rejected candidate not persisted;
- multiple candidates handled consistently;
- provider error mapped correctly;
- duplicate run is idempotent.

### 4. Repository integration tests

Against PostgreSQL:

- migrations apply cleanly;
- source message uniqueness;
- event insert/read;
- extraction run unique constraint;
- transaction rollback on failure.

### 5. API tests

Verify status codes and response bodies for:

- valid event;
- no event;
- validation rejection;
- malformed input;
- idempotent replay;
- provider failure.

### 6. OpenAI adapter contract tests

Mock provider response and verify:

- strict schema maps to domain models;
- malformed output is not silently accepted;
- timeout/retry behavior is bounded;
- provider-specific objects remain inside infrastructure layer.

### 7. Live evals

Opt-in command, e.g.:

```bash
make eval-live
```

or project equivalent.

Never make this mandatory for normal CI because it introduces cost, nondeterminism, and network dependency.

## Evaluation metrics

At dataset level compute:

- relevance precision;
- relevance recall;
- relevance F1;
- person extraction accuracy;
- location extraction accuracy;
- relation classification accuracy;
- certainty classification accuracy;
- whole-event exact match;
- false-positive rate on non-location messages;
- abstention precision/recall for missing-context cases.

For a pre-filter such as Stanza, **recall is the primary safety metric**: dropping a true location message before LLM is unrecoverable.

## Regression fixtures

Every production parsing incident should be reduced to an anonymized/minimized fixture that does not contain unnecessary personal data.
