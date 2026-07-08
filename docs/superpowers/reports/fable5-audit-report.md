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
