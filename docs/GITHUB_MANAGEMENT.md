# GitHub Management

## Branches

- `master`: stable branch; every push must pass CI.
- Feature branches: use `feature/<short-name>` for larger changes.
- Fix branches: use `fix/<short-name>` for targeted regressions.

## Required Checks

The CI workflow runs:

- Backend mock E2E.
- Localization workflow baseline tests.
- Glossary workflow baseline tests.
- Frontend TypeScript/Vite build.
- Browser E2E against a local FastAPI + Vite stack.

## Versioning

Update all three version markers together:

- `VERSION`
- `backend/app/main.py` FastAPI version
- `frontend/package.json`

Use annotated tags for releases:

```powershell
git tag -a v0.2.0 -m "Release v0.2.0"
git push origin v0.2.0
```

## Data Policy

Runtime data must stay outside the public repository:

- `D:\codex\localization-workflow-studio-data`
- uploaded workbooks
- generated workbooks
- SQLite databases
- logs
- `settings.local.json`
- API keys
