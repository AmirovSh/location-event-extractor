# AGENTS.md

## Mission

Реализовать надежный сервис, который превращает сообщения чата в проверяемые структурированные события о местоположении человека. Приоритет: корректность, трассируемость, возможность расширения и безопасная работа с чувствительными данными.

## Read first

Перед изменением кода прочитай в таком порядке:

1. `TASK.md`
2. `ARCHITECTURE.md`
3. `DOMAIN_MODEL.md`
4. `LLM_EXTRACTION_SPEC.md`
5. `DATABASE.md`
6. `TEST_STRATEGY.md`
7. `SECURITY_PRIVACY.md`
8. `DECISIONS.md`

Для задач, связанных с extraction/prompts/evals, дополнительно прочитай `skills/location-event-extraction/SKILL.md`.

## Engineering rules

- Не позволяй LLM напрямую изменять бизнес-состояние или выбирать окончательные DB identifiers.
- Сначала создавай typed candidate, затем валидируй/нормализуй deterministic code, затем persist.
- Любой сохраненный факт должен иметь provenance до исходного сообщения и evidence span.
- Система обязана уметь вернуть `unknown` / `ambiguous`; не форсируй догадки.
- MVP: одно сообщение, explicit person, explicit location. Не реализовывай full dialogue coreference раньше базовой версии.
- Stanza используй только за интерфейсом. Она не должна быть жестко связана с доменной логикой.
- Не делай premature microservices. Для MVP — modular monolith с четкими interfaces.
- Не добавляй vector DB, graph DB, Kafka или отдельный orchestration framework без доказанной необходимости.
- Любая новая зависимость должна иметь конкретное назначение и минимальный blast radius.
- Изменения схемы БД — только через миграции.
- Публичные модели API не должны быть ORM-моделями.

## Quality gates

Перед завершением изменений:

- formatter/linter проходят;
- type checks проходят, если настроены;
- unit tests проходят;
- integration tests проходят;
- новые branches extraction покрыты тестами;
- новые поля LLM schema имеют backward-compatible обработку или версионирование;
- логи не содержат секретов и полного текста сообщения по умолчанию;
- `git diff` проверен на accidental changes.

## Preferred implementation style

- Малые функции и явные типы.
- Dependency inversion для LLM provider, repository, NLP prefilter и clock.
- Pydantic models для boundaries/contracts.
- Domain enums вместо неограниченных строк.
- UTC внутри системы; исходный timezone и raw time expression сохранять отдельно.
- Idempotency по `source_message_id + extractor_version` или эквивалентному ключу.

## Tests

Каждый bug fix должен добавлять regression test. Для LLM-dependent logic разделяй:

- deterministic unit tests без сети;
- provider adapter tests с mock/fake;
- optional live evals, которые не входят в обязательный CI.

## Stop conditions

Не расширяй scope за пределы `TASK.md`. Если обнаружена неоднозначность, выбирай минимальное решение, совместимое с `ARCHITECTURE.md`, и документируй допущение в `DECISIONS.md` или ADR, если оно архитектурно значимо.
