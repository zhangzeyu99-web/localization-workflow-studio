# Getting Started

This guide runs Localization Workflow Studio locally with the public synthetic workbook. It keeps provider keys, runtime data, SQLite files, uploaded workbooks, and generated artifacts outside the repository.

## Requirements

- Python 3.11+
- Node.js 20+
- PowerShell on Windows
- Git

## Clone

```powershell
git clone https://github.com/zhangzeyu99-web/localization-workflow-studio.git
cd localization-workflow-studio
```

## Install Backend Dependencies

```powershell
python -m pip install -r backend\requirements.txt
```

## Install Frontend Dependencies

```powershell
cd frontend
npm ci
npm run build
cd ..
```

## Prepare Local Runtime Data

The default local data directory is:

```text
D:\codex\localization-workflow-studio-data
```

Create it before running real local workflows:

```powershell
New-Item -ItemType Directory -Force D:\codex\localization-workflow-studio-data
```

Copy the public config template if you need to edit provider settings:

```powershell
Copy-Item settings.example.json D:\codex\localization-workflow-studio-data\settings.local.json
```

Keep real API keys out of the repository, README screenshots, GitHub Pages, issues, and pull requests.

## Run Backend

```powershell
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Expected API base:

```text
http://127.0.0.1:8000
```

## Run Frontend

Open a second shell:

```powershell
cd localization-workflow-studio\frontend
npm run dev
```

Expected frontend URL:

```text
http://127.0.0.1:5173
```

## Try the Public Sample Workbook

Use:

```text
examples\synthetic-language.xlsx
```

Recommended first pass:

1. Create or select a sample project.
2. Import the synthetic workbook.
3. Review detected strings and glossary behavior.
4. Run the mock-safe workflow path for local smoke testing.
5. Review QA output before treating any workbook as delivery-ready.

The mock provider exists for CI, local E2E, and no-key validation only. It must not be used as real production translation output.

## Run Tests

All backend and integration tests:

```powershell
python -m pytest -q
```

Localization workflow tests:

```powershell
Push-Location workflow\localization
python -m pytest -q
Pop-Location
```

Glossary workflow tests:

```powershell
Push-Location workflow\glossary
python -m pytest -q
Pop-Location
```

Frontend build:

```powershell
cd frontend
npm run build
cd ..
```

Browser E2E after backend and frontend are running:

```powershell
cd frontend
$env:E2E_BASE_URL = "http://127.0.0.1:5173"
npm run e2e
```

## Common First-Run Issues

### Frontend cannot reach backend

Confirm the backend is running on:

```text
http://127.0.0.1:8000
```

Then restart the Vite dev server.

### Excel import fails

Use the public workbook first:

```text
examples\synthetic-language.xlsx
```

Real project workbooks may require project-specific column mapping and glossary setup.

### Provider output is blocked

This is expected when the provider is `mock` or when an API key is missing. Real delivery runs require a real provider configuration in the local runtime data directory.

### GitHub Pages looks static

That is expected. The Pages workbench is a public, read-only product surface. Full workflow execution requires the local backend.
