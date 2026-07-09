# Changelog

All notable changes are tracked here. The project uses semantic versioning while the public API is still pre-1.0.

## 1.1.1 - 2026-07-09

Workflow source-of-truth consolidation. `workflow/localization` and `workflow/glossary` are now declared sync artifacts mirrored from their standalone source repos; no product/backend behavior change.

- Established `D:\project\localization-workflow-project` (github.com/zhangzeyu99-web/localization-workflow) as the single maintenance source for the localization workflow. A month of studio-side evolution (large-text multilingual runner/gate/retro, module splits with re-export facades, AI-review helper dedup) was merged upstream together with the standalone repo's unpublished refactor (`utils/language_config.py` centralization, `term_rewrite_checker`, term-alias expansion, rich-text macro protection, th/vi support with VI in announcement `TARGET_LANGUAGES`), then mirrored back here.
- Added `scripts/sync_workflow_sources.py`: one command per target (`glossary` / `localization`) that mirrors the source repo into the embedded copy with exclusion rules, deletes out-of-scope leftovers, and hash-verifies every synced file on readback.
- Added `workflow/localization/SYNC.md` and rewrote `workflow/glossary/SYNC.md` as AI-readable sync contracts (source repo, sync command, verification gates); `AGENTS.md` now forbids editing the embedded copies directly.
- Post-sync gates all green: `workflow/localization` tests 174 passed + 25 subtests (now runnable from the repo root via a new `tests/conftest.py`), `workflow/glossary` tests 44 passed, backend suite 218 passed, ruff clean.

## 1.1.0 - 2026-07-09

Multi-user concurrency (backend) and a frontend optimization pass, planned in `docs/superpowers/plans/2026-07-08-multiuser-concurrency.md` and `docs/superpowers/plans/2026-07-08-frontend-optimization.md`.

Concurrency model — the workbench moves from one global "single long-text job" lock to per-project locking with a global cap, so a small team (2-10 people) can run tasks in different projects at the same time without stepping on each other:

- Enabled SQLite WAL journal mode for safer concurrent reads/writes, and closed a read-modify-write metadata race (`db.merge_run_metadata`) across ~15 call sites in runs/QA/multilingual/announcement flows.
- Evolved the single global job lease into a per-project lease `long_text:{project_id}`: different projects' translation/QA/announcement/model-fix jobs now run in parallel; the same project still serializes strictly (same guarantees for resumable runs, manifests, and harness files as before).
- Added a global concurrency cap `max_concurrent_ai_jobs` (default 2, adjustable 1-4) so provider budget, memory, and SQLite write pressure stay bounded even with many projects. Rejections now distinguish two reasons with distinct 409 copy: "project busy" (same project already running a task) vs "capacity" (workbench-wide cap reached).
- Added `GET /api/system/active-jobs`, returning every currently running job (lease name, job kind, project, start time) for UI surfaces and queueing hints.
- Added a process-wide shared rate limiter so concurrent runs against the same provider/API key share one RPM/TPM budget instead of each assuming exclusive access.
- Runs now snapshot `settings.local.json` once at start and use that snapshot throughout, so another user changing provider/preset mid-run no longer affects an already-started task.
- Added file-level locking around per-project shared JSON state (`project_harness.json`, `improvement_suggestions.json`) to close an edit window between the API thread and a background job.
- Project deletion is now refused with a clear 409 while a background job for that project is still active, instead of racing the job's file I/O.
- Fixed a pre-existing lease-name mismatch in `cancel_translation_run` so cancellation targets the correct lease.
- Added `scripts/concurrency_smoke.py`: an isolated-instance smoke test that runs two projects' translations in parallel, asserts both complete and are deliverable, asserts `/api/system/active-jobs` reports both running at once, asserts no `database is locked` errors, and asserts a third project is capacity-rejected once the default cap of 2 is reached.

Frontend optimization (F1-F4, purely UI/structure — no API or business-logic changes):

- **F1 (copy)**: added a centralized `uiText.ts` copy layer and operation-aware error fallback text; removed internal identifiers (status enums, field names, file paths, UUIDs, step numbers) from user-facing text; replaced native `window.alert`/`window.confirm` with an in-app `ConfirmModal`.
- **F2 (structure)**: split the ~2500-line `main.tsx` monolith and the ~2100-line `TranslationWizard.tsx` into focused modal, project-overview, per-domain action hook, and per-step wizard files with no behavior change.
- **F3 (performance)**: collapsed five overlapping polling loops behind shared hooks with `document.hidden` checks, in-flight de-duplication, and `AbortController`; paused the project-snapshot poll while a run is active; memoized hot-path components; code-split the three main wizard views; paginated run-history and project-activity lists.
- **F4 (visual)**: introduced a CSS custom-property design-token layer (color palette, spacing scale, radii, type scale) in `styles.css`, consolidated repeated card selectors onto shared base classes, and added a small-screen (~640px) breakpoint alongside the existing 980px one.

Active jobs panel (M4, frontend):

- The header now polls `GET /api/system/active-jobs` (every 9s, `document.hidden`-aware) and shows a quiet badge only while jobs are running; clicking it opens a panel listing each active job's project name, task type, and relative start time.
- The shared inline-status renderer now detects the `project_busy`/`capacity` 409 messages and appends a "查看活跃任务" action that opens the same panel, so a queued/rejected user can immediately see what is occupying the workbench.

Deployment closeout (M5):

- Replaced the "single instance, single task" constraint section in `docs/CLOUD_DEPLOYMENT.md` with a description of the new concurrency model (per-project lock, global cap, shared rate limiter, settings snapshot); kept the "single uvicorn worker, do not share SQLite across workers" constraint unchanged.
- Added multi-user concurrency test items to `docs/STABILITY_TEST_LIST.md` (parallel translation across projects, same-project mutual exclusion, capacity rejection, active-jobs visibility, restart lease recovery, settings-change isolation, delete-while-active guard) and a `docs/FEATURE_MATRIX.md` row for the concurrency surface.
- Version bump to 1.1.0 (MINOR: new user-visible concurrency capability) across `VERSION`, `backend/app/main.py`, `frontend/package.json`/`package-lock.json`, `README.md`; added `docs/releases/v1.1.0.md`.

## 1.0.4 - 2026-07-08

- Split the three thousand-line agent-side localization modules with zero behavior change: `utils/quality_harness.py`, `utils/announcement_docx_harness.py`, and `process_language.py` now delegate to focused submodules (`quality_harness_rules/terms`, `announcement_docx_common/terms/prepare/apply`, `process_language_terms/review/outputs`) while keeping every public symbol re-exported for backend subprocess callers and tests.
- Deduplicated the AI review batch helpers shared by `workflow/localization/cli.py` and `workspace_runner.py` into `utils/ai_checker.py` (`reset_review_dir`, `collect_recheck_rows`).
- Annotated every `workflow/localization` entry point with an explicit `Boundary:` marker (product runtime dependency vs agent-only) and corrected `CONTEXT.md` to match the backend's actual subprocess callers (`qa.py`, `translation.py`).
- Converted `workflow/glossary` into a declared sync artifact of the standalone `glossary-extraction-workflow` repository (v0.4.0): added `SYNC.md` with the sync command and no-direct-edit rule, synced the packaged `glossary_extraction/` refactor, and verified the copy by hash comparison plus an independent 44-test readback run.
- Recorded the dual-project review and optimization evidence in `docs/optimization/2026-07-08-dual-project-optimization.md`.

## 1.0.3 - 2026-07-07

- Documented and versioned the large-text multilingual local harness improvements for repository management.
- Hardened cache-lint coverage for machine-like bracket tokens, newline/font placeholders, CJK small-number and date filtering, Chinese/ASCII numeric units, language word multipliers, and large-number tolerance.
- Made retro reports explicitly distinguish skipped or waived gates from passed gates, including reason and alternative-check fields.
- Added long-task review signaling for runs over one hour so slow localization packs produce process evidence without automatically expanding the workflow.

## 1.0.0 - 2026-06-10

- Promoted Localization Workflow Studio to the first formal 1.0 release after the language-pack, QA, archive, delivery, quick-task, and announcement workflows were validated as one integrated workbench.
- Stabilized project AI analysis around structured Project Brief Markdown: uploaded project brief files now drive the project prompt and metadata directly, while ordinary requirement notes remain supporting evidence.
- Kept project prompts clean and delivery-oriented: term lists are excluded from the generic project prompt and continue to be injected per run through glossary snapshots, row-level `term_hits`, archive matches, and QA term bases.
- Preserved non-Codex operation boundaries: local harness, batching, QA, apply, archive, and delivery run inside the workbench backend; configured OpenAI/GPT-compatible or Claude providers handle only model-required steps.
- Locked the official 1.0 validation baseline: backend tests, workflow compile checks, Ruff fatal checks, frontend build, Playwright E2E, and forbidden Google/machine-translation scanning all pass locally before release tagging.

## 0.5.2 - 2026-06-08

- Added standalone stability tooling for local/LAN workbench runs, including start/stop scripts, a one-command stability check, and documented pass criteria for non-Codex operation.
- Verified the full project workflow against real sample files using the configured API provider: project creation, AI analysis, glossary import/export, translation, QA, archive import/export, quick task translation, and announcement delivery preparation.
- Kept frontend prompt display human-readable in Chinese while preserving the full execution prompt in backend snapshots for provider calls.
- Improved interrupted-run resume behavior and cleaned user-facing task/progress text so internal batch logs do not leak into quick-task and workflow surfaces.
- Extended E2E coverage for resumable translation, quick tasks, announcement workflow, language display, asset search/paging, delivery empty-state actions, and API failure feedback.


## 0.5.1 - 2026-06-04

- Added project-scoped quick tasks and announcement translation workflow support, including glossary extraction, constraint lookup, AI-response import, QA/apply/deliver shells, and EN/KR/JP-oriented delivery handling.
- Expanded multilingual asset handling with wide glossary/archive views, strong search, language-column controls, pagination, KR/JP display codes, and centralized language configuration through `/api/languages`.
- Hardened long-text AI orchestration with persistent batch fingerprints, local job leases, resumable/cancelable progress, provider rate limiting, and budget-aware batch execution.
- Consolidated provider calls so OpenAI uses Responses, Anthropic uses Messages, semantic QA/AI supplement/project analysis share one provider seam, and Google/external machine-translation paths remain absent.
- Hardened repository/runtime operations with streaming upload limits, SQLite foreign keys/indexes/dedupe, unified delivery naming helpers, frontend module extraction, and guardrail tests.
- Verified with backend tests, workflow harness tests, Ruff, frontend build, Playwright E2E, restart smoke, and forbidden-machine-translation scanning.

## 0.4.9 - 2026-05-21

- Reworked the GitHub Pages workbench entry to match the local product navigation: starting a new translation task now replaces the main project overview with the 9-step workflow view instead of opening a modal.
- Removed public "demo/full version/static" wording from the Pages workbench UI and status messages so the hosted page reads like the product surface.
- Kept the existing workbench controls and sample `小小战机` data while aligning the workflow step labels, back navigation, status strip, and step panel layout with the local app.

## 0.4.8 - 2026-05-21

- Added static GitHub Pages interactions to the workbench demo: settings modal, new project modal, 9-step task wizard, prompt edit/copy/regenerate controls, glossary import panel, term add/edit/delete, run detail toggle, QA action feedback, and delivery refresh feedback.
- Kept all interactions demo-only with visible status/toast feedback instead of pretending to call the backend.

## 0.4.7 - 2026-05-21

- Reworked the GitHub Pages demo to mirror the local workbench layout directly: same top header, sidebar, project overview, stat cards, tabs, glossary table, and static action feedback.
- Removed the separate marketing-style demo treatment so the public entry looks like the product UI rather than a standalone showcase page.

## 0.4.6 - 2026-05-21

- Added a GitHub Pages static demo entry using `小小战机` sample data, with read-only project tabs for metadata, glossary, translation, QA, delivery, and deployment guidance.
- Added GitHub Actions Pages deployment for the `docs/` homepage.
- Documented the full deployment split: static frontend, FastAPI backend, private metadata database, private file storage, and server-side provider secrets.
- Added a dedicated storage model document covering public repository boundaries, local runtime data, `.gitignore` coverage, and shared deployment storage recommendations.
- Added configurable backend CORS origins and `VITE_API_BASE_URL` frontend builds for separated frontend/backend deployments.
- Tightened generated glossary backfill so high-frequency term scans dedupe by normalized Chinese source text, conservatively fill only blank EN/EN2 fields, and surface pending-confirmation counts.
- Added model-first QA repair flow so configured GPT/Claude providers can propose row-level fixes before manual editing remains necessary.
- Cleaned workflow UI surfaces by hiding empty reference-material archive blocks and reducing raw QA labels in user-facing issue repair views.

## 0.4.5 - 2026-05-20

- Reworked the delivery page into final deliverable task cards instead of pending placeholder files.
- Added fixed per-run delivery filenames with project, language, timestamp, task type, short run ID, and final/changes suffixes.
- Added `task_code` support for A/T/QA task identities, including QA continuation inheriting the source translation task identity.
- Added `GET /api/projects/{id}/deliverables` so only QA-passed runs with final workbooks appear as deliverable tasks.
- Updated translation and QA history details to show the same task identity, source file, status, and QA summary fields used by delivery cards.

## 0.4.4 - 2026-05-20

- Added inline action status feedback near translation, QA, glossary, wizard, and delivery controls so button clicks have visible progress or result confirmation.
- Blocked wizard translation through the same provider/key guard used by the translation tab.
- Fixed glossary import category detection for Chinese `分类` headers and stopped using `imported` as a fallback category value.
- Updated browser E2E assertions to verify inline status feedback for upload, import, translation, QA, delivery, and manual fix actions.

## 0.4.3 - 2026-05-20

- Fixed translation history so glossary extraction/project brief runs no longer appear as completed translation tasks.
- Kept translation downloads tied to real QA-passed translation workbooks instead of prompt, brief, glossary, or other non-translation artifacts.

## 0.4.2 - 2026-05-20

- Completed the main workflow closure around project metadata, project glossary, translation, QA, and final delivery.
- Added run-level glossary, prompt, and Project Harness snapshots so translation and QA history can prove which inputs were used.
- Made translation runs register deliverable workbooks only after QA passes; direct QA now uses the project glossary snapshot and reports semantic QA as skipped when no provider key is configured.
- Tightened the UI around the reference layout: project tabs, glossary editing/import/export, translation history, QA continuation/import entry points, and delivery gate.
- Removed inactive history placeholder actions and kept user-facing delivery surfaces free of debug artifacts such as manifests, JSONL, raw workbooks, and input copies.
- Expanded backend, workflow, and Playwright E2E tests for glossary import/export, direct QA, manual fixes, mock-provider blocking, and final delivery generation.

## 0.4.1 - 2026-05-19

- Documented the formal translation evidence chain: prompt snapshot, workpack, response validation, workbook backfill, and final QA gate.
- Clarified that direct QA of an uploaded workbook is not evidence that Studio performed model translation.
- Kept real project translation blocked when the active provider is `mock` or a provider API key is missing.
- Fixed README version drift and added repository management follow-up tracking.
- Included the post-0.4.0 CI webserver conflict fix and small warplane project convergence fixes in the release line.

## 0.4.0 - 2026-05-19

- Added layered Project Harness support with global reusable gates separated from project-specific rules, style hints, manual fixes, and improvement suggestions.
- Added project asset roles and origins so uploaded, imported, generated, and manual workbooks or glossary assets can be selected per workflow step.
- Added glossary import preview, import, export, and editable term workflows.
- Added direct QA runs for existing translated workbooks, failed-row issue listing, manual fix application, QA reruns, and project improvement queues.
- Integrated project materials and notes into glossary extraction so project briefs and translation prompts can use multimodal-ready context.
- Hardened generated workbook metadata, mock placeholder preservation, QA failure artifact retention, browser E2E coverage, and README workflow documentation.

## 0.3.0 - 2026-05-19

- Replaced free-form provider configuration with GPT and Claude only.
- Added fixed fast, balanced, and deep-thinking presets for each provider.
- Added native Claude Messages API translation support.
- Updated GPT translation to use the Responses API with preset reasoning effort.
- Removed Gemini/Google from the provider plan and UI.

## 0.2.1 - 2026-05-19

- Moved the workflow diagram into the README for GitHub project introduction.
- Removed the workflow diagram tab from the local web app and kept the project overview focused on the three operational tabs.
- Added project artifact recovery in the wizard so uploaded workbooks and latest runs survive page refresh.
- Added reference asset upload, glossary term confirm/delete actions, run artifact links in history, and safer backend guards for uploads, downloads, glossary ownership, and active runs.

## 0.2.0 - 2026-05-19

- Added Playwright browser E2E coverage for the full web workflow.
- Added CI browser E2E orchestration with local backend and Vite servers.
- Fixed project stats so translated word counts and completed languages are based on artifacts and passed runs.
- Fixed run history dates to use stored run creation timestamps.
- Added repository governance docs, use cases, license, changelog, and version marker.

## 0.1.0 - 2026-05-19

- Initial public release of Localization Workflow Studio.
- Added React/Vite frontend and FastAPI backend.
- Integrated localization QA workflow and glossary extraction workflow.
- Added mock-provider EN translation loop, artifact archive, and CI baseline tests.
