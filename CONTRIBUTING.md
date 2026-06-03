# Contributing

Localization Workflow Studio is a local-first game-localization workflow project. Contributions should preserve the core safety boundary: public code and fixtures are allowed; real client workbooks, API keys, SQLite files, run logs, and generated private deliverables are not.

## Good First Contribution Areas

- Documentation improvements.
- Public synthetic examples.
- Workflow QA rules with focused tests.
- Glossary extraction and review improvements.
- Frontend usability fixes.
- Provider adapter hardening without exposing keys.
- CI and test reliability improvements.

## Local Setup

```powershell
git clone https://github.com/zhangzeyu99-web/localization-workflow-studio.git
cd localization-workflow-studio

python -m pip install -r backend\requirements.txt

cd frontend
npm ci
npm run build
cd ..
```

See [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) for the full local workflow.

## Data Safety Rules

Do not commit:

- real project workbooks,
- customer source strings,
- screenshots with unreleased game content,
- provider API keys,
- `settings.local.json`,
- SQLite databases,
- run logs,
- generated workpacks,
- QA reports from private projects,
- final delivery workbooks from private projects.

Use `examples/synthetic-language.xlsx` or new synthetic fixtures for public tests and documentation.

## Validation Commands

Run the checks that match your change.

Backend and integration tests:

```powershell
python -m pytest -q
```

Localization workflow:

```powershell
Push-Location workflow\localization
python -m pytest -q
Pop-Location
```

Glossary workflow:

```powershell
Push-Location workflow\glossary
python -m pytest -q
Pop-Location
```

Frontend:

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
cd ..
```

## Pull Request Checklist

- The change is limited to the stated scope.
- Public fixtures use synthetic data only.
- No secrets or private runtime artifacts are committed.
- README or docs are updated when behavior changes.
- Relevant tests or builds pass.
- The PR explains workflow impact: backend API, provider protocol, workpack protocol, QA output contract, and artifact paths.

## Issue Reports

For bugs, include:

- expected behavior,
- actual behavior,
- reproduction steps,
- OS and Python/Node versions,
- sanitized workbook structure when workbook import is involved,
- relevant logs with secrets removed.

For feature requests, describe the localization workflow problem first. Implementation ideas are welcome, but the problem statement matters more.
