# Fable5 Validation Log

All cases reviewed on 2026-07-08 at commit 064d730 (branch codex/fable5-full-audit-refactor). Environment: local Windows, isolated Tier D stack (backend 127.0.0.1:18000 with temp data root `.tmp/tier-d-data`, test-fake provider, Vite proxy on 127.0.0.1:5174). Cases were validated through the automated equivalents listed below plus the Tier D runtime checks; no case relied on memory or unverified claims.

## Case 001 new translation task: empty target language table to delivery

- Date: 2026-07-08
- Environment: Playwright e2e stack (test-fake provider) + Tier D stability_check
- Commit: 064d730
- Steps run: e2e "user can complete the EN localization workflow from project tabs" (22-test suite, --workers=1); stability_check steps 09-13 (upload empty-target table, readiness, translation run to terminal state, 2/2 rows completed, QA passed)
- Result: pass
- Evidence: e2e suite 22 passed (final Tier C run); stability-report.json steps 09-13 ok
- Follow-up: none

## Case 002 existing translated workbook direct QA

- Date: 2026-07-08
- Environment: same as 001
- Steps run: e2e "user can upload an existing translated workbook and run QA directly"; stability_check steps 14-16 (upload final_workbook, direct QA run reaches passed/failed terminal state)
- Result: pass
- Evidence: e2e 22 passed; stability steps 14-16 ok
- Follow-up: none

## Case 003 full language table glossary candidate generation

- Date: 2026-07-08
- Environment: Playwright e2e + backend pytest
- Steps run: e2e "translation workflow blocks full language table in project material and accepts it in step 4"; backend tests for preview/import/upload 400 guards; new classifier boundary test (1000/1001 rows)
- Result: pass
- Evidence: e2e 22 passed; test_complete_language_table_classifier_boundary 4 cases passed
- Follow-up: none

## Case 004 multilingual archive import/export

- Date: 2026-07-08
- Environment: Playwright e2e + backend pytest
- Steps run: e2e "project tabs show multilingual wide glossary and archive assets" and wide-glossary search/paging test; backend test_multilingual_orchestration + test_multilingual_delivery
- Result: pass
- Evidence: full pytest 172 passed; e2e 22 passed
- Follow-up: none

## Case 005 quick task translation

- Date: 2026-07-08
- Environment: Playwright e2e + Tier D stability_check
- Steps run: e2e quick-task QA and quick-task pasted-text translation tests; stability_check steps 20-22 (quick translation run to terminal state 2/2 rows)
- Result: pass
- Evidence: e2e 22 passed; stability steps 20-22 ok
- Follow-up: none

## Case 006 announcement TXT to delivery

- Date: 2026-07-08
- Environment: Playwright e2e + Tier D stability_check
- Steps run: e2e "project announcement workflow extracts terms with AI supplement and prepares delivery" (includes delivered-state/new-entry split assertions); stability_check steps 23-28 (create task, inspect constraints, extract terms, lookup, prepare)
- Result: pass
- Evidence: e2e 22 passed; stability steps 23-28 ok
- Follow-up: none

## Case 007 hard block recovery

- Date: 2026-07-08
- Environment: Playwright e2e + backend pytest
- Steps run: e2e manual-fix-flow.spec.ts (fail -> inspect -> risky delivery -> manual fix -> rerun -> pass); backend tests for delivered_with_issues archive source_type and the new cross-surface delivered_with_issues summary flag (translation + announcement parity)
- Result: pass
- Evidence: e2e 22 passed; test_deliverable_summaries_flag_delivered_with_issues and announcement force-delivery assertions passed in Tier C (172 passed)
- Follow-up: none

## Case 008 online/local smoke: version, health, upload, download, deletion

- Date: 2026-07-08
- Environment: Tier D stack (127.0.0.1:5174 via Vite proxy)
- Steps run: `python scripts/deployment_check.py --base-url http://127.0.0.1:5174 --expect-version 1.0.3 --check-frontend-assets` (version 1.0.3 + git_sha, frontend_assets match local dist 2/2, health writable, upload readability probe with clean CJK); `python scripts/stability_check.py --base-url http://127.0.0.1:5174` (all 28 steps ok: project create, uploads, translation, QA, exports/downloads, announcement, project deletion)
- Result: pass
- Evidence: deployment_check all 4 steps ok; stability-report.json at .tmp/stability/STABILITY-20260708133147, `deleted_project=proj_eeb62ec56205`
- Follow-up: pre-existing unrelated backend on port 8000 (real data root, started before this loop) was left untouched; Tier D used a dedicated port 18000 stack
