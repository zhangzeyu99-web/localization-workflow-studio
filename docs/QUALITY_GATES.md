# Quality Gates

This project separates generated translation evidence from direct QA evidence. A run is considered a formal Studio translation only when the translation pipeline produced the prompt snapshot, workpack, model response, validated workbook, and final QA report for the same run.

## Formal Translation Evidence

Required artifacts:

- `compiled_style_hint.txt`: project prompt plus project harness snapshot used by the run.
- `translation_workpack.jsonl`: source rows prepared for the provider with IDs, placeholders, tags, newline shape, terminology hits, UI metadata, and style hint.
- `translation_manifest.json`: input workbook fingerprint, row IDs, protocol, and target language metadata.
- `translation_response.jsonl`: provider response in strict `id + translation` JSONL format.
- Final workbook and QA report: written only after pre-backfill validation passes.

## Gate Order

1. Prompt gate: the run must compile the current project prompt and project harness before packaging rows.
2. Pre-translation gate: the workpack must include row-level constraints and input fingerprint.
3. Pre-backfill gate: the response must pass ID, order, placeholder, tag, newline, non-empty translation, and input drift validation.
4. Pre-delivery gate: global QA and project harness QA must finish with zero hard errors.

## Direct QA Runs

Uploaded translated workbooks can be checked directly. These runs produce QA evidence, but they do not prove that Studio performed the translation. UI and delivery surfaces should label these runs as imported-workbook QA.

## Test Fake Provider Boundary

The hidden test-fake provider is only for CI and no-key workflow regression. Product settings do not expose it; real project translation is blocked when a formal provider API key is missing.
