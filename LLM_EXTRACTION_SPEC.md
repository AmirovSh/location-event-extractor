# LLM extraction specification

## Purpose

The LLM translates natural-language semantics into a strict `LocationEventCandidate` contract. It must not choose database ids, mutate state, perform geocoding, or invent missing context.

## MVP input

```json
{
  "message_id": "msg-1001",
  "sent_at": "2026-08-31T10:15:00+05:00",
  "text": "Иван сейчас в Алматы"
}
```

No prior dialogue context is provided in MVP.

## Recommended output shape

Prefer a container that supports zero or multiple events:

```json
{
  "events": [
    {
      "person_mention": "Иван",
      "person_reference": "EXPLICIT",
      "location_mention": "Алматы",
      "location_reference": "EXPLICIT",
      "relation": "AT",
      "certainty": "ASSERTED",
      "polarity": "POSITIVE",
      "location_type": "CITY",
      "temporal_raw": "сейчас",
      "evidence_text": "Иван сейчас в Алматы",
      "evidence_start": 0,
      "evidence_end": 21,
      "ambiguous": false,
      "ambiguity_reason": null
    }
  ]
}
```

Offsets may be omitted in the first implementation if Unicode-safe span validation is not implemented yet; evidence text is mandatory.

## Extraction rules

1. Extract only physical location/movement of a person.
2. Do not infer location from preferences, topics, ownership, organization mentions, or hypothetical discussion.
3. The grammatical speaker is not automatically the subject.
4. Preserve the literal mention text; canonicalization belongs downstream.
5. If the person is only a pronoun/reference and cannot be resolved from the single message, set the candidate ambiguous or omit it.
6. If the location is only deictic/reference text such as `там`, `здесь`, `туда`, treat it as unresolved for MVP.
7. Distinguish assertion, probability, possibility, negation, and plan.
8. Distinguish current/presence relation from movement.
9. Do not fabricate dates from relative expressions. Preserve `temporal_raw`.
10. If the message contains multiple independent explicit events, return each separately.
11. Classify person/location mentions semantically as `EXPLICIT`, `REFERENCE`, or `UNKNOWN`.
12. Return semantic `polarity`; do not infer it downstream from word lists or phrase matching.

## Examples

### Positive AT

Input: `Иван сейчас в Алматы.`

Expected core fields:

```json
{
  "person_mention": "Иван",
  "location_mention": "Алматы",
  "relation": "AT",
  "certainty": "ASSERTED"
}
```

### Attribution

Input: `Иван сказал, что Мария в Астане.`

Expected subject: `Мария`, location: `Астане`.

Do not assign the location to `Иван` merely because he appears first.

### Negation

Input: `Иван не в Алматы.`

Expected:

```json
{
  "person_mention": "Иван",
  "location_mention": "Алматы",
  "relation": "AT",
  "certainty": "NEGATED"
}
```

### Modality

Input: `Наверное, Иван в Алматы.` -> `PROBABLE`.

Input: `Иван может быть в Алматы.` -> `POSSIBLE`.

### Plan

Input: `Иван завтра поедет в Алматы.` -> `TO` + `PLANNED`; `temporal_raw="завтра"`.

### Non-location

Input: `Иван любит Алматы.` -> no events.

Input: `Иван обсуждал аэропорт.` -> no events.

### Explicitness failure

Input: `Он в Алматы.` -> no persistable event in MVP.

Input: `Иван там.` -> no persistable event in MVP.

## Prompt design

Keep provider instructions concise and outcome-oriented. The important requirements are encoded by the JSON schema and the extraction rules above.

A suitable system/developer instruction conceptually states:

```text
You extract physical person-location events from one chat message.
Return only data matching the supplied schema.
Do not resolve missing context, invent entities, geocode, or choose database ids.
Preserve uncertainty, negation, movement direction, and the literal evidence.
When explicit person or explicit location is missing, abstain.
```

Avoid requesting hidden reasoning or chain-of-thought. If diagnostics are needed, expose only bounded categorical fields such as `ambiguity_reason`.

## Provider adapter

The provider adapter should expose a domain-level interface such as:

```python
class LocationEventExtractor(Protocol):
    async def extract(self, message: ParsedMessage) -> ExtractionResult: ...
```

The application/domain layers must not depend on OpenAI SDK response classes.

## Reliability controls

- strict schema / structured output;
- explicit timeout;
- bounded retries for transient provider failures only;
- request correlation id;
- prompt/schema versioning;
- metrics for empty/invalid/ambiguous outputs;
- fake extractor for CI.

## Evaluation set

Maintain fixtures grouped by:

- simple AT;
- movement TO/FROM/ARRIVED/LEFT;
- negation;
- uncertainty;
- future plans;
- attribution/nested clauses;
- non-location false positives;
- missing explicit person;
- missing explicit location;
- multiple events;
- punctuation/case/noisy chat text.
