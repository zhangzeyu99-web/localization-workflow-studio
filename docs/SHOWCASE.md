# Showcase

This showcase uses only public synthetic data. It is designed to help external users understand what Localization Workflow Studio does without exposing real game assets, client workbooks, provider keys, SQLite files, or run logs.

## Scenario

A small game team is localizing a fictional mobile shooter. The source team already maintains Excel language tables and needs a repeatable workflow for:

- project context,
- terminology,
- AI-assisted translation batches,
- placeholder and tag safety,
- QA review,
- final workbook delivery.

Public sample workbook:

```text
examples\synthetic-language.xlsx
```

Public read-only workbench:

```text
https://zhangzeyu99-web.github.io/localization-workflow-studio/
```

## Before

The typical manual workflow is fragile:

1. Source strings live in Excel workbooks.
2. Project context is scattered across notes, screenshots, and chat messages.
3. Prompts are copied manually into model providers.
4. Glossary decisions are remembered by people instead of enforced by checks.
5. QA findings are tracked outside the workbook.
6. Final delivery is hard to reproduce.

## Studio Workflow

Localization Workflow Studio turns that into a traceable local flow:

1. Create a project profile with game genre, target audience, style rules, and delivery expectations.
2. Import glossary terms or extract candidates from project material.
3. Import an Excel language table.
4. Generate a workpack with stable IDs, source strings, placeholders, tags, line-break shape, terminology hits, UI length hints, and input fingerprints.
5. Translate batches with a configured GPT or Claude provider.
6. Apply translations back only after ID, order, placeholder, tag, line-break, and fingerprint checks pass.
7. Run QA for hard issues before final delivery.
8. Archive reviewed translations and produce final workbook artifacts.

## What the Demo Proves

The public GitHub Pages workbench shows the product surface:

- project overview,
- prompt and project metadata,
- glossary review,
- translation workflow,
- QA feedback,
- translation archive,
- delivery area.

Because it is hosted publicly, it intentionally does not:

- upload workbooks,
- save project data,
- call model providers,
- include real client data,
- generate real deliverables.

## What Local Execution Adds

Running the backend locally enables:

- SQLite-backed project state,
- workbook upload and parsing,
- provider configuration,
- local workflow execution,
- generated workpacks,
- QA reports,
- final workbook output.

Start here:

```text
docs/GETTING_STARTED.md
```

## Safety Boundary

Use synthetic or approved public data in examples, screenshots, tests, GitHub issues, and pull requests.

Do not publish:

- real game workbooks,
- customer source strings,
- screenshots with unreleased content,
- provider API keys,
- SQLite databases,
- run logs,
- generated delivery artifacts from private projects.
