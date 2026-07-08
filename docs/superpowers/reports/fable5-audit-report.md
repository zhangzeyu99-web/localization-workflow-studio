# Fable5 Audit Report

## Product Invariants

- Formal Studio translation requires the same run to produce prompt snapshot, workpack, model response, validated workbook, and final QA report.
- Direct QA runs are valid QA evidence but do not prove Studio performed translation.
- Test fake provider is for CI/no-key regression only; formal project translation must be blocked when no formal provider key exists.
- Hard block must not be a dead end: users must be able to inspect issues, download issue artifacts, apply fixes, rerun QA, or produce explicitly risky issue delivery.
- Delivery surfaces must show only real downloadable final artifacts.
- Online/current deployment validation requires more than `/api/health`; `/api/version` and frontend/backend version match matter.
- Generated artifacts and metadata must not contain API keys.

## Source Map (Top 40 by lines)

| Lines | Path |
|---|---|
| 3777 | `backend\tests\test_workflow_e2e.py` |
| 3504 | `workflow\glossary\scripts\extract_glossary.py` |
| 2279 | `frontend\src\main.tsx` |
| 2051 | `frontend\src\components\translationWizard\TranslationWizard.tsx` |
| 1576 | `backend\app\db.py` |
| 1261 | `workflow\glossary\tests\test_extract_glossary_workflow.py` |
| 1076 | `backend\app\workflow\announcement.py` |
| 1035 | `workflow\localization\utils\announcement_docx_harness.py` |
| 992 | `backend\app\workflow\qa.py` |
| 954 | `frontend\src\components\announcement\AnnouncementWorkflow.tsx` |
| 875 | `workflow\localization\utils\quality_harness.py` |
| 850 | `workflow\localization\process_language.py` |
| 715 | `frontend\src\components\assets\ProjectAssetTabs.tsx` |
| 658 | `backend\app\workflow\delivery.py` |
| 648 | `workflow\localization\utils\ai_checker.py` |
| 612 | `backend\app\workflow\project_analysis.py` |
| 596 | `backend\app\workflow\asset_import_export.py` |
| 584 | `backend\tests\test_risk_hardening.py` |
| 528 | `workflow\localization\workspace_runner.py` |
| 527 | `backend\app\workflow\translation.py` |
| 524 | `workflow\localization\utils\large_text_multilingual_gate.py` |
| 519 | `backend\app\workflow\announcement_segments.py` |
| 505 | `workflow\localization\tests\test_quality_harness.py` |
| 499 | `frontend\src\components\project\ProjectMeta.tsx` |
| 498 | `workflow\localization\tests\test_announcement_docx_harness.py` |
| 491 | `backend\app\providers.py` |
| 484 | `workflow\localization\utils\translation_harness.py` |
| 445 | `workflow\localization\utils\term_checker.py` |
| 438 | `backend\app\workflow\announcement_outputs.py` |
| 437 | `frontend\src\types.ts` |
| 434 | `backend\app\routers\projects.py` |
| 431 | `workflow\localization\cli.py` |
| 407 | `backend\app\workflow\translation_orchestrator.py` |
| 391 | `backend\app\workflow\materials.py` |
| 365 | `frontend\src\domain\projectAssets.ts` |
| 360 | `backend\app\workflow\prompt_snapshots.py` |
| 360 | `backend\app\routers\shared.py` |
| 352 | `frontend\src\components\quickTask\QuickTaskWizard.tsx` |
| 328 | `workflow\localization\utils\readability_checker.py` |
| 325 | `workflow\localization\tests\test_term_checker.py` |

Note: the raw PowerShell `-Include *.py,*.tsx,*.ts` also matched `.pyc` files under `__pycache__` due to a legacy 8.3-filename wildcard quirk (`*.py` matching `*.pyc`). Those compiled-cache entries (e.g. `test_workflow_e2e.cpython-314-pytest-9.0.2.pyc` at 3694 lines) were filtered out of the table above as non-source noise.

## Invariant Verification Notes

**1. Formal translation run must produce snapshot + workpack + response + workbook + QA in the same run**
- `backend/app/workflow/translation.py` orchestrates the full pipeline in one run: preflight checks, snapshot creation (via `backend/app/workflow/prompt_snapshots.py`, not in the original read set but referenced from `translation.py`), term audit, workpack preparation, batch orchestration through `translation_orchestrator.py`, and post-translation QA invocation into `workflow/qa.py`.
- `backend/app/workflow/translation_orchestrator.py` drives async batch execution with retry/rate-limit handling and writes progress into run metadata, so the same `run_id` accumulates all artifacts (workpack, response, final workbook) rather than spreading them across runs.
- Contrast point: `backend/app/workflow/qa.py` also supports a **Direct QA** path (QA-kind run against an already-translated upload) that does not go through `translation.py` at all — this is the intended split enforcing invariant #2, not a violation of #1.

**2. Direct QA is valid QA evidence but not proof of Studio translation**
- Runs have a `kind` field (`translation` vs `qa`); `backend/app/routers/runs.py` and `backend/app/routers/qa.py` create/operate on these independently.
- `frontend/src/main.tsx` `runDirectQA` creates a `kind: 'qa'` run directly from an uploaded workbook, separate from `runTranslate`/`startMultilingualTranslationQueue`. The e2e test `user can upload an existing translated workbook and run QA directly` (`studio-ui-flow.spec.ts`) exercises exactly this path and confirms QA can pass without any translation run existing for that language.
- No code path was found that back-fills a fake `translation` run when only Direct QA has run — good, no violation found.

**3. Test-fake provider must not be usable for formal translation without a real key**
- `backend/app/providers.py` / `backend/app/config.py` define the `test-fake` provider as a distinct provider id.
- `frontend/src/components/translationWizard/TranslationWizard.tsx` has `formalTranslationBlockReason` which blocks the "formal-translate" action when no real provider key is configured.
- e2e test `real project formal translation is blocked without configured API credential` in `studio-ui-flow.spec.ts` explicitly sets `provider: 'openai'` with empty `api_key` and asserts `formal-translate` testid is disabled and a warning mentions `settings.local.json`.
- Caveat: several other e2e tests (e.g. `user can complete the EN localization workflow...`) explicitly set `provider: 'test-fake'` to drive CI runs — consistent with the invariant (test-fake is for CI, not silently usable in place of a real key in production).

**4. Hard block must not be a dead end**
- `backend/app/workflow/qa.py` exposes manual-fix and model-fix application functions (`apply_manual_fixes` / `apply_model_fixes` per prior read), reachable via `backend/app/routers/qa.py`.
- Frontend: `frontend/src/main.tsx` `applyManualFixes`/`applyModelFixes`, plus the QA step's `failed-row-editor` UI (exercised end-to-end in `frontend/e2e/manual-fix-flow.spec.ts`: fix a row, rerun QA, verify `passed`).
- An explicit "skip QA and archive anyway" escape hatch exists (`studio-ui-flow.spec.ts` test `user can explicitly skip QA and archive an existing translated language table`), gated behind a confirm dialog — this is the "explicitly risky issue delivery" path called for by the invariant.
- Delivery-side: `manual-fix-flow.spec.ts` shows a `delivery-problem-warning` surfaced when generating delivery with unresolved QA issues, and delivery is still generated (with a warning), not blocked outright — matches "not a dead end."

**5. Delivery surfaces must show only real downloadable final artifacts**
- `backend/app/workflow/delivery.py` and `backend/app/routers/delivery.py` build delivery packages from actual final workbook/QA artifacts on disk.
- Frontend empty state: `studio-ui-flow.spec.ts` test `delivery empty state routes to next actions` shows the delivery tab renders a `delivery-empty` state (not a fake/broken download link) when no deliverable exists yet, with buttons that route to Translate/QA/Archive tabs instead.
- No instance found where the UI renders a download link for an artifact that doesn't exist server-side; links are built from `Artifact` objects returned by the backend (`artifactDownloadHref` in `frontend/src/domain/artifacts.ts`, referenced but not in the original required-read list).

**6. Online/current deployment validation requires more than `/api/health`**
- `scripts/deployment_check.py` explicitly fetches `/api/version`, compares it against the local `VERSION` file (or an `--expect-version` override), and fails (`version_ok = False`) on mismatch — this directly enforces the invariant beyond a plain health check.
- `backend/app/routers/system.py` exposes `/api/version` and `/api/health` as separate endpoints; `/api/health` alone reports `ok`, storage writability, DB connectivity, and `provider_configured`, but does not carry version identity.
- `scripts/build_release_package.py`'s generated `ONLINE_DEPLOY_README.zh-CN.md` explicitly instructs operators to confirm `/api/version` matches and that "前端右下角显示 v{version}" (frontend footer shows the version) — i.e., the invariant is also documented as a manual/automated post-deploy check, not just enforced in one script.

**7. Generated artifacts and metadata must not contain API keys**
- `scripts/build_release_package.py` hard-excludes `settings.local.json`, `.env`, `api_key`, `api_key.txt`, and any filename containing `secret` from the release zip (`DEFAULT_EXCLUDE_NAMES`, `_should_skip`).
- `scripts/stability_check.py` checks provider settings via `settings.get("api_key") != "configured"` — i.e., the `/api/settings` endpoint is expected to return a redacted sentinel (`"configured"`), not the raw key, consistent with `backend/app/config.py`'s key-normalization helpers.
- No violation found in the reviewed files, but this was verified only for the settings/release-package surfaces; run metadata and prompt snapshots (`backend/app/workflow/prompt_snapshots.py`) were not in the required-read list and were not opened this pass, so metadata-level key leakage there is unverified (flagged as an open question, not a confirmed contradiction).

## Context Ingestion Notes

- **Backend architecture**: `backend/app/routers/*` is a thin HTTP layer that delegates to `backend/app/workflow/*` for actual business logic (translation, QA, delivery, announcement, glossary, project analysis, asset import/export). `db.py` is a single SQLite access layer (schema + CRUD) shared by all workflow modules; `jobs.py` implements singleton background jobs via DB leases, used for long-running translation/QA/announcement work. `providers.py` centralizes AI provider calls (OpenAI/Anthropic/test-fake) with prompt building and response parsing shared across translation, glossary, and announcement flows.
- **Frontend architecture**: `frontend/src/main.tsx` (2279 lines) is a single large `App` component holding most global state and orchestrating all workflow steps via direct `api()` calls (no Redux/Zustand-style store); feature areas are split into `components/translationWizard`, `components/announcement`, `components/assets`, `components/project`, `components/quickTask`, `components/shared`, with cross-cutting pure helpers under `frontend/src/domain/*` (e.g., `projectAssets.ts`, referenced heavily by `ProjectAssetTabs.tsx` and `ProjectMeta.tsx`, but not in the original required-read list).
- **workflow/localization and workflow/glossary CLI tools vs backend/app/workflow**: Per `AGENTS.md`, `workflow/localization` (gate/runner/retro/quality_harness/translation_harness) is explicitly an **agent-facing, non-runtime** toolset for large-text multilingual jobs, distinct from the product-runtime `backend/app/workflow/multilingual.py` and `translation_orchestrator.py`. This split is intentional and documented, not a contradiction. However, `workflow/glossary/scripts/extract_glossary.py` (3504 lines, largest source file outside tests) implements its **own** project-analysis and prompt-generation logic independent of `backend/app/workflow/project_analysis.py` and `backend/app/workflow/glossary.py` — this is a real duplication risk worth an Architect checkpoint (see below), since it's not clearly scoped as "agent tool only" the way the `workflow/localization` utilities are.
- **Test layout**: `backend/tests/test_workflow_e2e.py` (3777 lines) and `test_mock_e2e.py`, `test_risk_hardening.py` cover backend workflow end-to-end and hardening scenarios. `workflow/glossary/tests/` and `workflow/localization/tests/` cover the standalone CLI tools independently. `frontend/e2e/*.spec.ts` (Playwright) covers full-stack UI flows against a live dev server, using `provider: 'test-fake'` for deterministic runs and real `openai`/`anthropic` provider ids (with empty keys) specifically to test the "blocked without credential" paths — this is a good pattern for invariant #3 but means true real-provider integration is not covered by any test in the required-read set.
- **Surprising/notable**: (1) The source map surfaced several sizable files not in the required-read list that look architecturally relevant for Task 2 planning: `backend/app/workflow/announcement_segments.py` (519), `announcement_outputs.py` (438), `materials.py` (391), `prompt_snapshots.py` (360), and `frontend/src/domain/projectAssets.ts` (365). These should likely be in scope for deeper invariant/backlog verification in Task 2. (2) `frontend/src/styles.css` (2968 lines) was only spot-checked (first 150 lines) since it is pure CSS with no logic/invariant relevance — flagged here for transparency rather than claimed as fully reviewed.

## P0 User-Facing Failure Audit

### I-001 Upload errors show user-readable messages
- Files: `frontend/src/apiClient.ts` (`sanitizeUserFacingError`, `apiErrorText`, `api`), `frontend/src/main.tsx` (`upload`, line ~586: `上传失败：${errorText(error)}`), `backend/app/workflow/subprocess_runner.py` (`user_facing_error`), `backend/app/routers/projects.py` (upload endpoint, 413/400 paths), `backend/app/upload_storage.py` (`UploadTooLargeError`)
- Current behaviour: ALREADY FIXED. Backend maps errors through `user_facing_error()` before putting them in HTTP `detail`; the frontend runs every API failure through `apiErrorText`/`sanitizeUserFacingError`, which has explicit friendly mappings for unsupported file formats, 413 too-large, proxy/backend-down, missing-field 422s, and HTML error pages. `upload()` surfaces the sanitized text in the status line and returns null instead of throwing.
- Risk: If a new backend error string is added without a mapping, the user sees the raw (truncated to 240 chars) message — degraded but not leaking.
- Existing tests: `backend/tests/test_risk_hardening.py::test_upload_streaming_rejects_oversized_file_and_sanitizes_name` (413 + name sanitization); `frontend/e2e/studio-ui-flow.spec.ts` "new project modal shows API failure instead of silently staying stuck" (500 detail surfaced readably).
- Missing tests: No unit tests exist for `sanitizeUserFacingError` / `apiErrorText` mapping table (frontend has no unit-test layer at all, only Playwright). No e2e uploading an unsupported suffix and asserting the friendly message.
- Recommended fix: none needed, add regression test only (a small vitest or e2e case for the unsupported-format and 413 messages).
- Validation: `python -m pytest backend/tests/test_risk_hardening.py -q`; `cd frontend && npx playwright test studio-ui-flow.spec.ts`
- Priority: P2

### I-002 Frontend must not expose traceback, command, or server paths
- Files: `backend/app/workflow/subprocess_runner.py` (`user_facing_error` strips `Traceback`, `command failed`, `python.exe`, drive-letter paths; `run_subprocess` writes raw stderr to `runs/<id>/logs/subprocess_error.json` instead of the response), `frontend/src/apiClient.ts` (`sanitizeUserFacingError` second-layer regex for `Traceback|[A-Za-z]:[\\/]`), all routers wrap exceptions via `user_facing_error(exc)` before `HTTPException.detail`.
- Current behaviour: ALREADY FIXED, two-layer defense. Verified all routers route exception text through `user_facing_error` (59 call sites in `announcement.py` alone). Raw diagnostics go to per-run log files.
- Risk: A router author adding a new endpoint could `raise HTTPException(500, str(exc))` directly and bypass the helper — no structural enforcement, only convention.
- Existing tests: `test_risk_hardening.py::test_subprocess_failure_writes_structured_backend_error_without_raw_user_text`, `::test_subprocess_reads_structured_error_user_message`, `::test_subprocess_event_output_summarizes_qa_dict`.
- Missing tests: No cross-router property test asserting that error `detail` payloads never contain `Traceback` / drive-letter paths for a sample of failing requests.
- Recommended fix: none needed, add regression test only. (The 59x try/except boilerplate is a Depth problem — see Candidate A — but not a user-facing failure today.)
- Validation: `python -m pytest backend/tests/test_risk_hardening.py -q`
- Priority: P2

### I-003 Delivery page shows only real downloadable artifacts
- Files: `backend/app/workflow/delivery.py` (`list_project_deliverables` skips runs whose final artifact path does not exist or has 0 translated rows; `_merged_deliverable_summaries` and `_announcement_deliverable_summaries` also check `Path(...).exists()`), `backend/app/db.py` (`get_artifact` exposes `exists` flag), `frontend/src/main.tsx` (`refreshDeliverables`/`loadDeliverables` render only backend-returned deliverables).
- Current behaviour: ALREADY FIXED. Existence and non-empty checks are enforced server-side before anything reaches the delivery UI; the empty state routes users to next actions rather than showing dead links.
- Risk: Low. A file deleted between listing and click would still 404, but the artifact download router returns a sanitized message and `apiClient` maps "artifact file missing" to a friendly message.
- Existing tests: `test_risk_hardening.py::test_delivery_skips_empty_workbook_but_keeps_failed_review_artifact`, `::test_artifact_payload_exposes_file_existence`; `frontend/e2e/studio-ui-flow.spec.ts` "delivery empty state routes to next actions".
- Missing tests: None critical; optionally a test that a deliverable disappears from `/api/projects/{id}/deliverables` after its file is deleted on disk.
- Recommended fix: none needed, add regression test only.
- Validation: `python -m pytest backend/tests/test_risk_hardening.py -q`
- Priority: P2

### I-004 Full language table import is not mistaken for project glossary
- Files: `backend/app/workflow/asset_import_export.py` (`is_complete_language_table_for_glossary_import`, `guard_complete_language_table_for_glossary_import`, `guard_complete_language_table_for_project_material`, applied inside `preview_glossary_import` and import), `backend/app/routers/projects.py` (upload seam applies the project-material guard and rejects with 400), `frontend/src/components/assets/ProjectAssetTabs.tsx` (`GlossaryToolsPanel` explains "完整语言表不会直接写入项目术语库").
- Current behaviour: ALREADY FIXED. One central classifier with guards at all three entry seams (upload as term_base, glossary preview, glossary import); full tables can only produce candidates for manual confirmation.
- Risk: Low; classifier heuristics could misfire on unusual tables, but the failure mode is a clear 400 with guidance, not silent pollution.
- Existing tests: `backend/tests/test_workflow_e2e.py` (~lines 2586-2628: preview/import/upload of a full language table all 400 with "完整语言表" detail; project-material rejection); `frontend/e2e/studio-ui-flow.spec.ts` "translation workflow blocks full language table in project material and accepts it in step 4".
- Missing tests: A boundary-case test for the classifier itself (e.g., what row/column threshold flips a glossary-shaped file into "complete language table").
- Recommended fix: none needed, add regression test only.
- Validation: `python -m pytest backend/tests/test_workflow_e2e.py -q -k language_table`
- Priority: P2

### I-005 Glossary import state refreshes from actual stored rows
- Files: `frontend/src/main.tsx` (`importGlossaryArtifact`, line ~743: after POST it awaits `refreshProjectSnapshot(projectId)` so the table re-reads stored rows), `backend/app/routers/glossary.py` (import returns `imported_count`/`languages`).
- Current behaviour: ALREADY FIXED. The glossary table is re-rendered from the refreshed project snapshot (server-stored rows), not from the optimistic import payload.
- Risk: Low. `refreshProjectSnapshot` failure would leave the count in the status line but a stale table until next refresh.
- Existing tests: `frontend/e2e/studio-ui-flow.spec.ts` "project glossary import auto-detects EN KR JP into one wide row" and "quick workflow can preview and import glossary terms" (both assert stored rows via UI table and via `GET /glossary` API).
- Missing tests: None needed.
- Recommended fix: none needed.
- Validation: `cd frontend && npx playwright test studio-ui-flow.spec.ts`
- Priority: P2

### I-006 Announcement completed state differs from new task entry
- Files: `frontend/src/components/announcement/AnnouncementWorkflow.tsx` (`unfinishedAnnouncementTasks` excludes `delivered` from the default task pick at workflow entry, line ~190: `const tasks = initialTaskId ? allTasks : unfinishedAnnouncementTasks(allTasks)`; `announcementTaskCanCancel` returns false for delivered; `AnnouncementDeliveryStep` renders "已生成公告交付包...不会重复生成新交付" and hides the generate button when delivered), `frontend/src/main.tsx` (`openAnnouncementTask` passes an explicit task id only from "查看交付").
- Current behaviour: ALREADY FIXED. A fresh workflow entry never lands on a delivered task; delivered tasks are view-only via "查看交付" and show no "继续" button.
- Risk: Low.
- Existing tests: `frontend/e2e/studio-ui-flow.spec.ts` announcement test asserts `.announcement-current-task` has count 0 after delivery, the delivered row has "查看交付" and no "继续", and re-entering the workflow shows the STEP 1 材料 panel.
- Missing tests: None needed.
- Recommended fix: none needed.
- Validation: `cd frontend && npx playwright test studio-ui-flow.spec.ts -g "announcement"`
- Priority: P2

### I-007 Hard block recovery path is standardized
- Files: `backend/app/workflow/qa.py` (manual/model fix application, issue artifacts), `backend/app/routers/qa.py` (fix endpoints), `backend/app/workflow/delivery.py` (`build_delivery_package` archives failed-QA output with `source_type: delivered_with_issues`), `frontend/src/main.tsx` (`applyManualFixes`, `applyModelFixes`, `skipQAArchive`), `AnnouncementWorkflow.tsx` (`announcementHardBlockerCount` + "生成带 QA 摘要的交付包" path).
- Current behaviour: PARTIAL. Every hard-block surface has a working recovery path: failed-row editor + rerun QA, downloadable issue/change artifacts, risky delivery with warning (`delivery-problem-warning`), skip-QA archive with confirm dialog, and announcement issue-delivery. But each surface implements its own variant (translation QA vs announcement vs skip-QA) with different wording and metadata — recovery exists everywhere, standardization does not.
- Risk: Inconsistent UX and inconsistent audit metadata (e.g. `delivered_with_issues` vs announcement QA-summary-only) make it harder to know which deliveries carried known issues.
- Existing tests: `frontend/e2e/manual-fix-flow.spec.ts` (full fail → inspect → risky delivery → manual fix → rerun → pass loop); `test_risk_hardening.py::test_failed_qa_delivery_archives_translation_with_issue_source`; skip-QA e2e in `studio-ui-flow.spec.ts`.
- Missing tests: A test asserting announcement issue-delivery also marks its archive/metadata as issue-carrying (parity with `delivered_with_issues`).
- Recommended fix: Smallest scoped change: unify the "delivered with known issues" metadata marker across translation and announcement delivery paths (data-level standardization first, UI wording second). Relates to Candidate B.
- Validation: `python -m pytest backend/tests/test_risk_hardening.py -q` + `npx playwright test manual-fix-flow.spec.ts`
- Priority: P1

### I-008 Online version consistency is visible/checkable
- Files: `backend/app/routers/system.py` (`/api/version` returns `version` from VERSION file, `git_sha`, `frontend_assets` — actual dist asset filenames), `frontend/src/main.tsx` (`refreshRuntimeVersion` + `runtime-version-badge` renders `v{version}` from the backend), `scripts/deployment_check.py` (compares `/api/version` against local VERSION or `--expect-version`, fails on mismatch), `scripts/build_release_package.py` (deploy README mandates the check).
- Current behaviour: PARTIAL. Backend version is visible in the UI badge and checkable by script, and `/api/version` exposes `frontend_assets` so a script *can* compare served asset hashes with the package. But nothing automatically verifies that the frontend bundle the browser loaded matches the backend version (the badge just displays whatever the backend says — a stale cached frontend with a new backend shows the new version), and `deployment_check.py` does not currently assert `frontend_assets` against the local dist.
- Risk: After deployment, a stale CDN/browser-cached frontend can silently run against a newer backend while the badge claims the new version.
- Existing tests: `test_risk_hardening.py::test_version_endpoint_returns_runtime_version` (asserts version + frontend_assets shape). No test for mismatch detection.
- Recommended fix: Smallest scoped change: embed the build version into the frontend bundle (Vite define) and have the badge warn when it differs from `/api/version`; extend `deployment_check.py` to compare `frontend_assets` with local `frontend/dist/assets`.
- Missing tests: deployment_check unit test with a mismatched version/asset fixture.
- Validation: `python -m pytest backend/tests/test_risk_hardening.py -q -k version`; manual `python scripts/deployment_check.py --base-url ...`
- Priority: P1

### I-009 Project deletion refreshes list and selected project
- Files: `frontend/src/main.tsx` (`deleteProject`, line ~414: DELETE → re-fetch `/api/projects` → recompute `nextId` → reset view/tab when the active project was deleted; stale "not found" answers trigger `refreshProjects()` instead of an error dead-end), `DeleteProjectModal` + long-press `delete-hold` guard.
- Current behaviour: ALREADY FIXED in code. List refresh, selection fallback, view reset, and the stale-deletion race are all handled.
- Risk: Low; regression risk only, since nothing pins this behaviour.
- Existing tests: none. No e2e test exercises project deletion at all (grep of `frontend/e2e` for delete/删除 found nothing); backend delete endpoint is covered in `test_workflow_e2e.py` but not the frontend refresh behaviour.
- Missing tests: An e2e: create two projects, delete the active one via modal, assert the list refreshes and the other project (or empty state) becomes active.
- Recommended fix: none needed, add regression test only.
- Validation: new Playwright case in `studio-ui-flow.spec.ts`
- Priority: P2

### I-010 AI flows check provider before creating formal runs
- Files: `frontend/src/domain/providerSettings.ts` (`aiProviderConfigurationReminder`, `isAiProviderReady`, `FORMAL_AI_PROVIDERS`), `frontend/src/components/translationWizard/TranslationWizard.tsx` (`formalTranslationBlockReason` disables `formal-translate`), `frontend/src/components/quickTask/QuickTaskWizard.tsx` (reminder before start), `AnnouncementWorkflow.tsx` (AI 翻译 disabled + reminder), `backend/app/workflow/translation.py` (preflight, line ~102: real provider without `api_key` → run set to `needs_input` with reason, no provider call).
- Current behaviour: ALREADY FIXED with one nuance. Frontend gates all three launch surfaces; backend preflight independently refuses to call a real provider without a key and parks the run as `needs_input` (not a dead formal run). Nuance: `FORMAL_AI_PROVIDERS` includes `test-fake`, and backend preflight only enforces keys for `REAL_PROVIDERS` — so a machine with provider=test-fake can run "formal" translation. That is exactly what CI e2e relies on; production is protected by `deployment_check.py --require-provider` plus operator configuration, not by code.
- Risk: A misconfigured production deployment left on test-fake would produce fake "formal" runs. Policy decision (Architect): should cloud deployment_mode hard-refuse test-fake formal runs?
- Existing tests: `frontend/e2e/studio-ui-flow.spec.ts` "real project formal translation is blocked without configured API credential" and "announcement AI translation shows API reminder when provider is not configured".
- Missing tests: Backend test that a translation run with provider=openai and empty key ends `needs_input` without calling the provider; a test pinning the cloud+test-fake policy once decided.
- Recommended fix: none needed for the key check; the test-fake-in-cloud policy is an Architect decision, not a bug fix.
- Validation: `cd frontend && npx playwright test studio-ui-flow.spec.ts -g "blocked"`
- Priority: P2 (P1 if Architect decides cloud must refuse test-fake)

## Module Deepening Candidates

### A: User-facing error Module
- Files: `backend/app/errors.py`, `backend/app/workflow/subprocess_runner.py` (`user_facing_error`), every file in `backend/app/routers/*` (~180 `HTTPException` sites, 59 in `announcement.py` alone), `frontend/src/apiClient.ts` (`sanitizeUserFacingError`, `apiErrorText`).
- Problem: The error-sanitization Implementation lives at two Seams (backend helper + frontend regex table) with overlapping but diverging rules — a Locality problem: adding one new error mapping means editing two files in two languages, and drift already exists (backend passes `api_key` errors through raw; frontend has extra mappings for proxy/413/HTML). The router-level `except ValueError → HTTPException(400, user_facing_error(exc))` pattern is copy-pasted boilerplate: the Interface each router must know is too wide. Notably, the `UserFacingError` hierarchy in `errors.py` exists but no router or app-level exception handler dispatches on it — a Seam that was built and never wired.
- Solution direction (no Interface design): concentrate sanitization + HTTP-status mapping behind one backend Seam (e.g. an app-level exception Adapter for `UserFacingError`), keeping the frontend table as defense-in-depth only.
- Benefits: Leverage — every existing and future router endpoint gets correct sanitized errors with zero per-endpoint code; Locality — one place to audit for path/traceback leaks.
- Tests: parametrized router test asserting no `Traceback`/drive-letter path in any error detail; mapping-table unit tests.
- Friction: high (most-touched boilerplate in the codebase). Executor recommendation: implement.

### B: Delivery artifact Module
- Files: `backend/app/workflow/delivery.py` (`list_project_deliverables`, `_merged_deliverable_summaries`, `_announcement_deliverable_summaries`, `_artifact_delivery_file`), `backend/app/routers/shared.py` (`_attach_delivery_downloads`, `attach_delivery_item_downloads`), `backend/app/db.py` (`get_artifact` `exists` flag), `backend/app/download_urls.py`.
- Problem: The "is this artifact real and downloadable" rule is enforced consistently but re-implemented as inline `Path(...).exists()` checks in at least four places plus the `exists` flag in db.py. Locality is acceptable today (delivery.py concentrates most of it) and tests pin the behaviour. The bigger friction found in the I-007 audit is metadata inconsistency between translation issue-delivery (`delivered_with_issues`) and announcement issue-delivery (QA summary only) — a Depth gap in the delivery summary shape, not in existence checking.
- Solution direction: consolidate existence checks on the db `exists` flag and unify the issue-carrying delivery marker across surfaces.
- Benefits: Leverage — one truthy signal for "downloadable"; Locality — issue-delivery audits read one field.
- Tests: deliverable-disappears-when-file-deleted test; announcement issue-delivery metadata parity test.
- Friction: medium (driven by I-007). Executor recommendation: narrow-first (metadata unification only; existence checking already deep enough).

### C: Provider readiness Module
- Files: `frontend/src/domain/providerSettings.ts` (`FORMAL_AI_PROVIDERS`, `aiProviderConfigurationReminder`), `backend/app/workflow/translation.py` (preflight `REAL_PROVIDERS` + `api_key` check), `backend/app/config.py` (`normalize_provider_name`), `backend/app/routers/system.py` (`/api/health` `provider_configured`).
- Problem: The "is the provider ready for formal work" rule lives at three Seams — a frontend list, a backend preflight, and a health field — each with its own Implementation. The frontend `FORMAL_AI_PROVIDERS` and backend `REAL_PROVIDERS` can drift silently (they already differ in intent: frontend includes test-fake as launch-ready). There is no single Adapter the UI can ask "why is formal translation blocked" — the frontend recomputes it from raw settings.
- Solution direction: a single backend-owned readiness signal (already partially exists in `/api/health`) consumed by all frontend gates; the cloud+test-fake policy from I-010 belongs here.
- Benefits: Leverage — all three launch surfaces plus health/deploy checks share one truth; Locality — policy changes (e.g. blocking test-fake in cloud) become a one-file change with one test.
- Tests: backend readiness matrix test (provider × key × deployment_mode); e2e keeps the blocked-button assertion.
- Friction: medium. Executor recommendation: narrow-first (backend readiness field + frontend consumption; policy decision required from Architect first).

### D: Full language table classification Module
- Files: `backend/app/workflow/asset_import_export.py` (`is_complete_language_table_for_glossary_import` + two guard wrappers), call seams in `routers/projects.py` (upload) and glossary preview/import.
- Problem: honestly, none material. The classifier is a single Implementation with thin guard Adapters applied at every entry Seam, backend and frontend tests pin the behaviour, and the I-004 audit found no drift. The Interface (one boolean question) is already narrow and the Depth is adequate.
- Solution direction: nothing structural; optionally add classifier boundary-case unit tests.
- Benefits of acting now: marginal.
- Tests: boundary-threshold unit test only.
- Friction: none. Executor recommendation: defer.

### E: Large text product gate Module
- Files: `workflow/localization/utils/large_text_multilingual_gate.py` (`preflight`, `cache_lint`, `apply_dry_run`, `readback_gate`), `large_text_multilingual_runner.py`, `large_text_multilingual_retro.py` (agent-side); `backend/app/workflow/multilingual.py`, `translation_orchestrator.py`, `qa.py` (product-side).
- Problem: The deterministic gates (cache-lint before write-back, apply-dry-run, delivery readback) exist only as agent CLI tooling; product multilingual runs rely on the QA harness and delivery checks instead. This is a Locality split by design (AGENTS.md declares the CLI non-runtime), but the 2026-07-07 productization plan explicitly wants these gates product-side. Today a product-run Large Text Pack does not get a Delivery Readback equivalent to the agent path.
- Solution direction: port the gate checks (not the runner/manifest machinery) as an internal product Module invoked by multilingual delivery — an Adapter over the same fixture logic, with the CLI becoming a second caller.
- Benefits: Leverage — product runs gain the same deterministic guarantees the agent workflow has; Locality — one gate Implementation instead of a product/agent fork.
- Tests: gate-parity fixtures (same workbook through CLI gate and product gate produce identical verdicts).
- Friction: medium (scope is a feature, not a refactor). Executor recommendation: narrow-first (readback gate only, per the productization plan; Architect must scope).

### F: Frontend workflow state Module
- Files: `frontend/src/main.tsx` (2279 lines: all global state, 60+ handler functions, per-project busy/status maps), `frontend/src/components/translationWizard/TranslationWizard.tsx` (2051 lines), prop-drilling of ~30 callbacks into `ProjectOverview`/`Wizard`.
- Problem: `App` is a shallow but enormous Module — its Interface (the prop lists passed down) is nearly as large as its Implementation. Locality is poor: adding any workflow action touches main.tsx state, handler, and two prop chains. However, behaviour is heavily pinned by Playwright e2e, and the `domain/*` pure-helper layer already extracts the logic that most needed extracting.
- Solution direction: incremental extraction of per-domain hooks (glossary, delivery, announcement) that own their API calls and status lines — not a global store rewrite.
- Benefits: Leverage — new features stop paying the main.tsx tax; Locality — a glossary bug becomes a one-folder search.
- Tests: existing e2e is the safety net; no new test type required, but extraction should land one domain at a time with e2e green between steps.
- Friction: high (maintenance) but risk of a big-bang refactor is also high. Executor recommendation: narrow-first (one domain hook as a pilot).

## Fable5 Architecture Checkpoint Decision (Task 2.4)

Input given to Fable5: Product Invariants, P0 audit summary, Module Deepening Candidates A-F, CONTEXT.md, current git status. Not the full repo.

Question: Which Module deepening candidates should be approved for implementation, which should be deferred, and which require narrower Interfaces before executor implementation?

Decisions:

- **Candidate A (user-facing error Module): APPROVED, narrow Interface.** Wire the existing `UserFacingError` hierarchy in `backend/app/errors.py` to an app-level FastAPI exception handler in `backend/app/main.py` (the Seam that was built and never wired). Do NOT mass-edit the ~180 router `HTTPException` sites — that is a broad rewrite and is rejected. Existing status codes and detail strings pinned by tests must not change. Add a cross-router regression test asserting no `Traceback`/drive-letter path in error details. Rationale: gains the Seam and Locality for future endpoints at near-zero regression risk.
- **Candidate B (delivery artifact Module): APPROVED, narrow scope = I-007 metadata parity only.** Announcement issue-delivery must record an issue-carrying marker equivalent to translation's `delivered_with_issues`. Additive metadata only; no field removal; existence-checking Implementation is already deep and must not be restructured. Required validation: Tier B plus a parity regression test.
- **Candidate C (provider readiness Module): DEFERRED except one regression test.** Policy ruling on I-010: cloud-mode hard refusal of test-fake formal runs is NOT adopted in this loop — CI e2e and no-key regression depend on test-fake, and production protection already exists via `deployment_check.py --require-provider` plus operator configuration. Executor adds one backend regression test: translation run with provider=openai and empty key ends `needs_input` without a provider call. Readiness-signal unification is deferred to a future loop.
- **Candidate D (language table classification): DEFERRED.** No material friction; optionally one classifier boundary unit test if cheap.
- **Candidate E (large text product gate): DEFERRED with narrow reason.** Product delivery already enforces existence + non-empty translated-row checks before exposing downloads (`list_project_deliverables`), which covers the user-facing invariant. Full gate parity (cache-lint/apply-dry-run/readback as a product Module) is feature-scale work owned by the 2026-07-07 productization plan and must not be done as a refactor batch in this loop.
- **Candidate F (frontend workflow state Module): DEFERRED.** `main.tsx` is shallow-but-huge, but behaviour is pinned by Playwright e2e only; hook extraction is a cross-flow frontend state redesign with high regression cost and no user-facing gain in this loop. Revisit when a feature batch already has to touch a domain's state.

Approved batch order for Task 3 (maps plan order onto audit findings):

1. I-002 + Candidate A narrow: wire `UserFacingError` handler + cross-router no-leak regression test.
2. I-001: regression test for upload error mapping (backend 413/unsupported-format detail sanity).
3. I-003: regression test — deliverable disappears from listing when file deleted on disk.
4. I-010: regression test — real provider without key parks run as `needs_input`.
5. I-007 + Candidate B narrow: announcement issue-delivery metadata parity + test.
6. I-008: embed build version in frontend bundle, badge mismatch warning, `deployment_check.py` asserts `frontend_assets`.
7. I-009: Playwright e2e for project deletion refresh/selection.
8. I-004: classifier boundary unit test (optional; drop if flaky to construct).

Required validation: Tier A every batch; Tier B for batches 1, 5, 6; Tier C every three commits and before completion; Tier D before final report.

## Non-runtime Tooling Scope Note

Architect decision recorded for this loop: `workflow/glossary/scripts/extract_glossary.py` (3504 lines) is agent-side tooling that intentionally runs parallel to the backend runtime (`backend/app/workflow/glossary.py`, `project_analysis.py`), in the same way `workflow/localization/*` utilities are declared non-runtime in AGENTS.md. The scope for this audit loop is **documentation only** — record the boundary (done here and in CONTEXT.md domain terms) — not merging the implementations and not deprecating the CLI. Any convergence work is a separate future decision.
