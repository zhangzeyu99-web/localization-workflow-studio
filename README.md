# Localization Workflow Studio

[![CI](https://github.com/zhangzeyu99-web/localization-workflow-studio/actions/workflows/ci.yml/badge.svg)](https://github.com/zhangzeyu99-web/localization-workflow-studio/actions/workflows/ci.yml)

Local web studio for game localization workflows. It combines project onboarding, project prompt generation, glossary extraction, EN translation workpack generation, model-provider translation, strict QA, and artifact history.

![Use-case map](docs/assets/use-case-map.svg)

## What It Integrates

This repository is the product shell around two workflow codebases:

- [`zhangzeyu99-web/localization-workflow`](https://github.com/zhangzeyu99-web/localization-workflow)
- [`zhangzeyu99-web/glossary-extraction-workflow`](https://github.com/zhangzeyu99-web/glossary-extraction-workflow)

The copied workflow code lives under:

```text
workflow/localization
workflow/glossary
```

The web app and backend adapter live outside those workflow folders so upstream workflow changes can be re-applied with a narrow adapter check.

## Current Scope

- Frontend: React + Vite.
- Backend: FastAPI + SQLite.
- Provider protocols: Chat Completions by default, Responses optional.
- Default provider: `mock`, so local and CI tests do not need an API key.
- True v1 closed loop: EN translation.
- Other languages: visible configuration entry only; they do not pretend to be completed by automation.

## Data Policy

Runtime data is outside the public repository:

```text
D:\codex\localization-workflow-studio-data
```

This directory stores uploaded workbooks, generated workbooks, logs, SQLite, project files, artifacts, and `settings.local.json`.

## Quick Start

```powershell
cd D:\codex\localization-workflow-studio
python -m pip install -r backend\requirements.txt

cd frontend
npm ci
npm run build
cd ..

python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd D:\codex\localization-workflow-studio\frontend
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

## Provider Settings

Public repository files only include `settings.example.json`. Runtime secrets are stored in:

```text
D:\codex\localization-workflow-studio-data\settings.local.json
```

Default settings use `mock`. For a real provider, open the web settings modal and configure:

- provider: `openai-compatible`
- protocol: `chat-completions` or `responses`
- base URL
- API key
- model
- batch size

## Test Matrix

Run backend and workflow tests:

```powershell
python -m pytest -q
python -m pytest -q workflow\localization
python -m pytest -q workflow\glossary
```

Run frontend build:

```powershell
cd frontend
npm run build
```

Run browser E2E after local backend and frontend are running:

```powershell
cd frontend
$env:E2E_BASE_URL = "http://127.0.0.1:5173"
npm run e2e
```

Replay a recent real project with mock provider:

```powershell
cd frontend
$root = "C:\Users\Administrator\Desktop\本地化处理\明日2_5.15"
$env:E2E_BASE_URL = "http://127.0.0.1:5173"
$env:E2E_SOURCE_WORKBOOK = Join-Path $root "2.0欧美翻译需求0515NT全语.xlsx"
$env:E2E_TERM_WORKBOOK = Join-Path $root "明日2术语表.xlsx"
npm run e2e
```

## Documentation

- [Use cases](docs/USE_CASES.md)
- [Iteration model](docs/ITERATION.md)
- [GitHub management](docs/GITHUB_MANAGEMENT.md)
- [Changelog](CHANGELOG.md)
- [License](LICENSE)

## Version

Current version: `0.2.0`

Version markers:

- `VERSION`
- `backend/app/main.py`
- `frontend/package.json`

See [GitHub management](docs/GITHUB_MANAGEMENT.md) for release and tag rules.
