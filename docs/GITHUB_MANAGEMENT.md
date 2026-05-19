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

For patch releases that only update documentation, CI orchestration, or management metadata, still update all version markers if the release is tagged.

## Issue Management

Use GitHub issues for every known gap that affects user acceptance. Keep issues small enough to close with one focused PR.

Suggested labels:

- `type:bug`: product behavior is incorrect or misleading.
- `type:enhancement`: a new user-facing capability.
- `area:frontend`: UI, copy, navigation, or browser workflow.
- `area:backend`: API, data model, artifacts, settings, or run orchestration.
- `area:qa`: quality harness, validation, manual fixes, or reports.
- `area:docs`: README, release notes, governance, or examples.
- `priority:p0`: blocks real delivery.
- `priority:p1`: blocks acceptance or causes serious confusion.
- `priority:p2`: important but not blocking.

Release issues should include:

- current behavior
- expected behavior
- validation command or browser flow
- affected artifacts, if any

## Release Checklist

Before tagging:

1. `python -m pytest -q`
2. `Push-Location workflow\localization; python -m pytest -q; Pop-Location`
3. `Push-Location workflow\glossary; python -m pytest -q; Pop-Location`
4. `cd frontend; npm run build`
5. Browser E2E when the change touches UI or workflow orchestration.
6. Confirm GitHub Actions passes after push.
7. Create a GitHub release with the validation summary.

## Data Policy

Runtime data must stay outside the public repository:

- `D:\codex\localization-workflow-studio-data`
- uploaded workbooks
- generated workbooks
- SQLite databases
- logs
- `settings.local.json`
- API keys
