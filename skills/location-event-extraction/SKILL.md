---
name: location-event-extraction
description: Implement, review, test, or evaluate extraction of person-location events from chat messages, including relations, modality, provenance, validation, and future context resolution.
---

# Location Event Extraction Skill

Use this skill when working on semantic extraction, prompts, schemas, validation rules, eval fixtures, regression cases, entity/coreference roadmap, or model-quality analysis for this repository.

## Required context

Read:

1. `../../../DOMAIN_MODEL.md`
2. `../../../LLM_EXTRACTION_SPEC.md`
3. `../../../TEST_STRATEGY.md`
4. `references/EXTRACTION_CASES.md`

## Workflow

### 1. Classify the change

Determine whether the task affects:

- relevance detection;
- semantic extraction;
- relation classification;
- certainty/modality;
- explicit-person/location validation;
- evidence/provenance;
- entity resolution;
- temporal reasoning;
- evaluation only.

Do not modify unrelated layers.

### 2. Preserve the candidate boundary

The model may return mentions and semantics only. Never add logic that lets the LLM choose canonical database ids or persist data directly.

### 3. Add/modify the typed contract first

If a new semantic field is needed:

1. define its domain meaning;
2. update enum/schema;
3. define unknown/abstention behavior;
4. update deterministic validation;
5. update fixtures/evals;
6. then update provider prompt/adapter.

### 4. Test semantic contrasts

For every new extraction behavior add at least one positive and one contrastive negative example.

Example: if supporting `ARRIVED`, test both `Иван приехал в Алматы` and `Иван обсуждает поездку в Алматы`.

### 5. Prefer abstention over fabrication

Missing person/location context, ambiguous referents, and unsupported deictic mentions must result in no persistable candidate or an explicit ambiguous state.

### 6. Evaluate regression risk

Check at minimum:

- false-positive location mentions;
- wrong subject attribution;
- negation/modality collapse;
- movement misclassified as presence;
- hidden dependency on prior dialogue in MVP;
- evidence mismatch.

### 7. Finish with verification

Run deterministic tests. If a live model eval is available, run it only when explicitly configured and compare metrics to the previous baseline. Do not block standard CI on network access.

## Output expectations for reviews

When reviewing extraction changes, report:

- semantic behavior changed;
- schema changes;
- new/updated fixtures;
- metrics or deterministic test results;
- known ambiguity/remaining edge cases.
