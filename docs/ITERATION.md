# Iteration Model

Localization Workflow Studio is maintained as an integration shell around two upstream workflow projects:

- `zhangzeyu99-web/localization-workflow`
- `zhangzeyu99-web/glossary-extraction-workflow`

## Release Rules

- `PATCH`: bug fixes, documentation updates, non-breaking QA rule updates.
- `MINOR`: new workflow capabilities, new UI surfaces, new provider features, or adapter changes.
- `MAJOR`: reserved for post-1.0 breaking changes.

## Update Loop

1. Pull or copy upstream workflow changes into `workflow/localization` or `workflow/glossary`.
2. Record the upstream commit in the change note or release body.
3. Run backend mock E2E, both upstream baseline suites, frontend build, and browser E2E.
4. Update `CHANGELOG.md` and `VERSION` when the change is user-visible.
5. Push to GitHub and verify Actions before tagging a version.

## Compatibility Boundary

The backend adapter expects these contracts to remain stable:

- `run_translation_harness.py` emits `translation_workpack.jsonl`, `translation_manifest.json`, and accepts a JSONL response.
- Translation provider output remains JSONL with `id` and `translation`.
- `run_quality_harness.py --json` returns a JSON object with `passed`, `issues`, and `failures`.
- `extract_glossary.py` accepts ID/source/target column parameters and emits glossary detail, final glossary, project brief, and prompt artifacts.

If an upstream change breaks one of these contracts, update `backend/app/workflow.py` in the same release.
