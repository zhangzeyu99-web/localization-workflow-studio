# Use Cases

![Localization Workflow Studio use-case map](assets/use-case-map.svg)

This page uses only public synthetic data. It is meant to show how the Studio should be evaluated without exposing private workbooks, customer strings, provider keys, local file paths, SQLite databases, or run logs.

## 1. Static Product Review

Use this when you want to understand the product surface without installing anything.

```text
https://zhangzeyu99-web.github.io/localization-workflow-studio/
```

Expected result:

- The product positioning is visible in the first viewport.
- Public links point to the workflow guide, Excel QA guide, setup guide, sample case, and GitHub repository.
- The demo shows project metadata, glossary review, AI translation workflow, QA feedback, archive, and delivery areas.
- No file upload, provider call, or private data persistence happens in the hosted demo.

## 2. Local Mock Workflow

Use this before every workflow integration change and before trying a real provider.

```powershell
git clone https://github.com/zhangzeyu99-web/localization-workflow-studio.git
cd localization-workflow-studio

python -m pip install -r backend\requirements.txt

cd frontend
npm ci
npm run build
```

Then follow:

```text
docs/GETTING_STARTED.md
```

Expected result:

- The backend runs on `http://127.0.0.1:8000`.
- The frontend runs on `http://127.0.0.1:5173`.
- The public synthetic workbook can be used for a smoke test.
- Mock output is allowed only for local validation, CI, and E2E checks.
- Mock output is not treated as real production translation.

## 3. Excel Translation QA Review

Use this when a translated workbook already exists and you want a local QA pass.

Input:

```text
examples/synthetic-language.xlsx
```

Expected result:

- Workbook rows keep stable IDs.
- Glossary terms are checked for consistency.
- Placeholder, tag, line-break, and UI-length risks are reported.
- QA output can be reviewed before any workbook is considered delivery-ready.

## 4. Real Provider Smoke

Use this only after local provider configuration is ready.

Requirements:

- `settings.local.json` is stored outside the repository.
- A valid GPT or Claude provider key is available locally.
- A small synthetic workbook is used first.

Expected result:

- Provider output follows the strict JSONL line protocol.
- Apply checks reject missing IDs, duplicate IDs, placeholder drift, tag drift, line-break drift, and stale input fingerprints.
- Final workbook generation is allowed only after QA gates pass.

## What Not To Publish

Do not publish:

- real customer workbooks,
- unreleased game strings,
- private screenshots,
- provider API keys,
- SQLite runtime databases,
- local absolute file paths,
- generated delivery artifacts from private projects.

Public examples should use synthetic or explicitly approved data only.
