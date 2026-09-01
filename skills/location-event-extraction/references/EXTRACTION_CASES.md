# Extraction reference cases

These cases define semantic intent, not exact provider wording.

## Presence

`Иван в Алматы.`
- person: Иван
- location: Алматы
- relation: AT
- certainty: ASSERTED

`Мария сейчас в офисе.`
- person: Мария
- location: офисе
- relation: AT
- certainty: ASSERTED
- temporal_raw: сейчас

## Movement

`Петр приехал в Астану.`
- relation: ARRIVED

`Анна едет в аэропорт.`
- relation: TO
- do not mark confirmed AT

`Сергей вышел из офиса.`
- relation: LEFT (preferred) or FROM if implementation documents mapping

## Uncertainty and negation

`Иван не в Алматы.`
- relation: AT
- certainty: NEGATED

`Наверное, Иван в Алматы.`
- certainty: PROBABLE

`Иван может быть в Алматы.`
- certainty: POSSIBLE

## Future intent

`Иван завтра поедет в Алматы.`
- relation: TO
- certainty: PLANNED
- temporal_raw: завтра

## Wrong-attribution traps

`Иван сказал, что Мария в Астане.`
- event subject: Мария
- not Иван

`Анна написала: "Петр сейчас в аэропорту".`
- event subject: Петр

## Non-location false positives

`Мне нравится Алматы.` -> no event.

`Иван вспоминает Москву.` -> no event.

`Мария работает над проектом Астана.` -> no event unless text explicitly denotes physical presence.

`Петр купил билет в Алматы.` -> travel evidence/intent is not confirmed physical location.

## MVP missing-context cases

`Он в Алматы.` -> abstain/reject: explicit person missing.

`Иван там.` -> abstain/reject: explicit location missing.

`Я здесь.` -> out of scope unless the product explicitly maps author -> person and context -> location in a future phase.

## Conditional/hypothetical

`Если Иван будет в Алматы, позвони.` -> not confirmed AT.

`Представь, что Иван в Алматы.` -> no confirmed event.

## Multiple events

`Иван в Алматы, а Мария в Астане.`
- two independent AT events if multi-event extraction is enabled.

`Иван уехал из Алматы и приехал в Астану.`
- LEFT/FROM Алматы
- ARRIVED Астана

## Future context cases — not MVP

`Саша прилетел вчера. Он сейчас в Алматы.`
- requires person coreference: Он -> Саша.

`Саша приехал в Астану. Он будет там до пятницы.`
- requires person + location coreference and temporal interval normalization.
