# Engineering task: Location Event Extractor MVP

## Goal

Создать backend-компонент, который принимает уже распарсенное сообщение чата и извлекает из него структурированное утверждение о физическом местоположении **явно указанного человека** в **явно указанном месте**.

Пример входа:

```json
{
  "conversation_id": "conv-42",
  "message_id": "msg-1001",
  "author_id": "user-5",
  "sent_at": "2026-08-31T10:15:00+05:00",
  "text": "Иван сейчас в Алматы"
}
```

Ожидаемый смысловой результат:

```json
{
  "person_mention": "Иван",
  "location_mention": "Алматы",
  "relation": "AT",
  "temporal_raw": "сейчас",
  "certainty": "ASSERTED",
  "evidence_text": "Иван сейчас в Алматы"
}
```

После deterministic validation/normalization результат может быть сохранен как `LocationEvent`.

## MVP scope

### Must have

1. HTTP endpoint или application service для обработки одного сообщения.
2. Typed input/output contracts.
3. LLM extractor с structured output.
4. Возможность подменить LLM fake implementation в тестах.
5. Validation layer, который не сохраняет incomplete/ambiguous candidates.
6. Сохранение `LocationEvent` и provenance.
7. PostgreSQL schema + migrations.
8. Idempotent repeated processing одного сообщения одной версией extractor.
9. Enum для semantic relation как минимум:
   - `AT`
   - `TO`
   - `FROM`
   - `LEFT`
   - `ARRIVED`
   - `NEAR`
   - `UNKNOWN`
10. Enum certainty как минимум:
   - `ASSERTED`
   - `PROBABLE`
   - `POSSIBLE`
   - `NEGATED`
   - `PLANNED`
   - `UNKNOWN`
11. Evidence span/text и ссылка на source message.
12. Набор deterministic tests и extraction fixtures.
13. README с локальным запуском.

### Explicitly out of scope for MVP

- multi-message dialogue reasoning;
- pronoun resolution (`он`, `она`, `они`);
- person alias resolution (`Саша` -> `Александр Петров`);
- location coreference (`там`, `здесь`);
- geocoding внешними сервисами;
- автоматическое определение координат;
- полноценная нормализация относительного времени;
- duration inference;
- conflict reconciliation между несколькими событиями;
- graph database;
- vector database;
- background streaming ingestion.

## Behavior

### Accepted examples

- `Иван в Алматы.`
- `Мария находится в офисе.`
- `Петр приехал в Астану.`
- `Анна едет в аэропорт.` — может быть `TO`/`PLANNED` или иной документированный mapping.
- `Сергей вышел из офиса.` — `FROM` или `LEFT` согласно выбранной семантике.

### Must not silently persist as positive current-location fact

- `Мне нравится Алматы.`
- `Иван не в Алматы.`
- `Кажется, Иван в Алматы.` без сохранения соответствующей certainty.
- `Иван может быть в Алматы.` без сохранения соответствующей certainty.
- `Он в Алматы.` — explicit person отсутствует для MVP.
- `Иван там.` — explicit location отсутствует для MVP.
- `Иван сказал, что Мария в Астане.` — extractor должен корректно связать location с Марией, а не с Иваном.
- `Иван думает о поездке в Алматы.` — не утверждение текущего физического положения.

## Persistability rule

Candidate разрешено превратить в persisted `LocationEvent`, только если:

- есть явный `person_mention`;
- есть явный `location_mention`;
- есть evidence;
- relation распознана;
- candidate не помечен как ambiguous;
- schema validation проходит.

`NEGATED`, `PROBABLE`, `POSSIBLE`, `PLANNED` могут сохраняться как события, если бизнес-правило это допускает, но **не должны автоматически обновлять derived current location как достоверное текущее состояние**.

## API expectation

Рекомендуемый endpoint:

`POST /v1/location-events/extract`

Response должен разделять extraction и persistence outcome, например:

```json
{
  "message_id": "msg-1001",
  "candidate": {
    "person_mention": "Иван",
    "location_mention": "Алматы",
    "relation": "AT",
    "certainty": "ASSERTED",
    "temporal_raw": "сейчас",
    "evidence_text": "Иван сейчас в Алматы",
    "ambiguous": false
  },
  "persisted": true,
  "event_id": "...",
  "rejection_reason": null
}
```

Точный transport contract может отличаться, если это обосновано в коде и документации.

## Interfaces expected

Минимально выделить abstractions, эквивалентные:

- `LocationCandidateDetector` — optional pre-filter.
- `LocationEventExtractor` — semantic extraction.
- `CandidateValidator` — deterministic validation.
- `LocationEventRepository` — persistence.
- `Clock` — тестируемое время/normalization anchor.

Person/Location resolvers можно определить как interfaces/stubs для будущего, но не реализовывать сложную логику в MVP.

## LLM provider

Если используется OpenAI:

- использовать Responses API;
- использовать strict structured output / JSON schema;
- model name и параметры должны настраиваться через environment/config;
- не хардкодить API key;
- timeout/retry должны быть ограниченными;
- provider-specific types не должны протекать в domain layer.

## Observability

Добавить structured logs для:

- received message metadata;
- filter decision;
- extractor invocation outcome;
- validation result;
- persistence result;
- latency/error category.

Не логировать полный текст сообщений по умолчанию. Допускается message id, hashes, token/length metadata и redacted evidence.

## Definition of Done

MVP считается готовым, когда:

1. Новый разработчик может поднять сервис по README.
2. Миграции поднимают чистую БД.
3. Endpoint/application service принимает пример сообщения.
4. Fake extractor позволяет полностью тестировать pipeline без API key.
5. Реальный LLM adapter реализован, конфигурируем и выдает только typed candidate.
6. Candidate validation предотвращает прямую запись мусора в БД.
7. Повторная обработка того же `message_id` не создает неконтролируемые дубликаты.
8. Для каждого event сохраняется source provenance.
9. Тесты покрывают positive, negative, uncertain, movement, explicitness и attribution cases.
10. `pytest`/equivalent проходит локально.
11. Архитектура не блокирует roadmap из `docs/ROADMAP.md`.
