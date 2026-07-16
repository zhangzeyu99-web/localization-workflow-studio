# Online Operator Attribution Implementation Plan

> **Goal:** Give every online AI task a visible operator nickname, surface that ownership in active-job/conflict UI, and ship a verified v1.3.3 operations package.

**Architecture:** Keep the existing lightweight `X-Operator` request attribution. Add one always-visible header control for managing the nickname, require it only when cloud users start or resume background AI work, and snapshot it into the database-backed job lease so ownership survives refreshes and process boundaries. This remains attribution, not authentication.

**Tech Stack:** FastAPI, SQLite, React, TypeScript, Playwright, pytest, Vite.

---

## Task 1: Persist and expose job ownership

**Files:**
- Modify: `backend/app/db.py`
- Modify: `backend/app/jobs.py`
- Modify: `backend/app/routers/system.py`
- Modify: `backend/app/routers/shared.py`
- Test: `backend/tests/test_concurrency_lease.py`

1. Add failing tests proving a lease stores `operator_name`, `/api/system/active-jobs` returns it, and a same-project conflict names the current operator.
2. Run `py -3.14 -m pytest backend/tests/test_concurrency_lease.py -q` and confirm the new assertions fail for missing ownership.
3. Add the additive SQLite column/migration, snapshot the current operator when acquiring a lease, enrich active-job payloads, and include ownership in project-busy conflict details with a legacy fallback.
4. Re-run the focused test file and confirm it passes.

## Task 2: Require a nickname for cloud AI work

**Files:**
- Modify: `backend/app/operator_context.py`
- Modify: `backend/app/routers/runs.py`
- Modify: `backend/app/routers/qa.py`
- Modify: `backend/app/routers/announcement.py`
- Modify: `backend/app/workflow/multilingual.py`
- Test: `backend/tests/test_operator_attribution.py`

1. Add failing tests proving cloud background starts without `X-Operator` return a clear client error before task state changes, while a named request can start.
2. Run the focused tests and confirm failure is caused by the missing cloud guard.
3. Add one shared `require_operator_for_cloud()` guard and call it at every background translation, QA/model-fix, announcement, and multilingual start boundary before mutation.
4. Re-run the focused tests and the concurrency tests.

## Task 3: Add an independent operator control and recovery action

**Files:**
- Add: `frontend/src/components/system/OperatorIdentityControl.tsx`
- Modify: `frontend/src/operator.ts`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/SettingsModal.tsx`
- Modify: `frontend/src/components/system/ActiveJobsPanel.tsx`
- Modify: `frontend/src/components/shared/WorkflowPrimitives.tsx`
- Modify: `frontend/src/types.ts`
- Test: `frontend/e2e/studio-ui-flow.spec.ts`

1. Add failing Playwright coverage for the always-visible nickname control, persistence, active-job operator display, and the "set nickname" recovery action.
2. Run the selected Playwright tests and confirm they fail because the controls/fields do not exist.
3. Implement the compact header control and modal, remove the duplicate settings field, show `operator_name` in active jobs, and route operator-required errors to the same modal.
4. Re-run the selected Playwright tests and run the frontend type/build checks.
5. Perform visual QA at desktop and narrow viewport widths, checking header wrapping, focus, dialog readability, and status actions.

## Task 4: Version, regression verification, and release package

**Files:**
- Modify: `VERSION`
- Modify: `backend/app/main.py`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Add: `docs/releases/v1.3.3.md`

1. Update all version surfaces to `1.3.3` and document the operator-attribution change and deployment notes.
2. Run the repository's full backend and frontend verification commands, then run package verification.
3. Review the final diff against the design and ensure no unrelated refactor is included.
4. Commit the implementation so the release manifest records an exact clean Git SHA.
5. Build a hidden-settings online deployment archive with `scripts/build_release_package.py`, validate the archive, compute/check the SHA-256 sidecar, and report exact artifact paths to operations.
