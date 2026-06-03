# Synthetic Examples

This directory contains public, fictional data for demos, smoke tests, docs, and issue reproduction.

## `synthetic-language.xlsx`

`synthetic-language.xlsx` is a small language table for validating the basic EN workflow without exposing real game strings.

Columns:

- `ID`
- `cn`
- `en`

The English column is intentionally blank so the Studio can exercise the EN full-translation workflow with the mock provider.

## How to Use It

1. Start the backend and frontend with the steps in `docs/GETTING_STARTED.md`.
2. Create or select a sample project.
3. Import `examples/synthetic-language.xlsx`.
4. Run the mock-safe workflow path for local validation.
5. Review QA output before treating any workflow as delivery-ready.

## Fixture Rules

Examples in this directory must stay synthetic.

Do not add:

- real project workbooks,
- customer source text,
- unreleased game screenshots,
- provider API keys,
- SQLite files,
- run logs,
- final delivery workbooks from private projects.
