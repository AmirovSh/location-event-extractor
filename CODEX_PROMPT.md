# Initial prompt for Codex

Implement the project described in `TASK.md` and obey `AGENTS.md`.

Start by inspecting the repository and reading the referenced design documents. If the repository is empty, bootstrap the MVP using the default stack described in `README.md`. If code already exists, integrate with the existing stack and conventions instead of rewriting unrelated parts.

Implement the MVP end-to-end, including schema/migrations, typed domain models, the extraction boundary, deterministic validation, persistence, API surface, tests, and developer documentation.

Important constraints:

- One input message only for MVP.
- Only explicit person + explicit location must be accepted as a persistable location event.
- LLM output is a candidate, never a direct DB write.
- Preserve source provenance and evidence.
- Support abstention/ambiguity.
- Keep Stanza optional and behind a replaceable interface.
- Do not implement dialogue coreference, graph DB, or temporal interval inference beyond the minimal raw-time fields required by the MVP.
- Make the code ready for the next roadmap phases without pre-implementing them.

Before finishing, run the relevant quality gates and report:

1. what was implemented;
2. architecture/file structure;
3. tests/commands run and their results;
4. remaining roadmap items;
5. any assumptions or deviations from the docs.
