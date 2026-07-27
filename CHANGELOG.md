# Changelog

All notable changes are tracked here. The project uses semantic versioning while the public API is still pre-1.0.

## 1.7.0 - 2026-07-27

Proper-name extraction and bilingual-source workflow release.

- Added explicit `cn`, `cn+en`, and `en` source modes across standard translation, AI review, workspace execution, and the large-text multilingual workflow; source mode and English references now participate in manifests, caches, checkpoints, and request fingerprints.
- Added category-driven skill-name and location-name policies with compactness, collision, and readability warnings while keeping meaning and established terminology authoritative.
- Expanded glossary extraction with low-frequency proper-name retention, skill/location classification, current-language-table translation priority, delivery-quality review packets, and clean-delivery gates.
- Preserved canonical game-name constraints across translation and QA so exact titles such as `Legend of Mushroom` cannot drift into pluralized, expanded, or recomposed variants.
- Updated glossary backfill to consume the generated target-language header while retaining compatibility with legacy artifacts that used `EN` for every language.
- Produced account-enabled and no-account cloud artifacts from the same clean commit and frontend build.

## 1.6.4 - 2026-07-24

Game-name terminology and announcement QA fix release.

- Read every `Chinese_PRC` / `Chinese_PRC.N` source alias in complete language tables, so alternate Chinese game names map to the same canonical target.
- Added confirmed project glossary terms to announcement constraints and made task edits, project terms, and selected language tables take precedence over historical translation archives.
- Applied occurrence-aware longest-term matching: overlapping short aliases are suppressed while independent later nickname uses remain available.
- Made announcement `term_hits` binding in prompts and QA, prevented sentence templates from overriding them, and stopped the hard-blocker repair step from appending a correct term to an otherwise wrong translation.
- Rebuilt unprovenanced v1.6.3 announcement-term caches from current trusted constraints while preserving imported terms and AI supplements.
- Hardened formal language-table QA so Unicode word substrings do not count as term hits; exact game-name categories block inflected names without rejecting normal pluralized common terms.
- Produced account-enabled and no-account cloud artifacts from the same clean commit and frontend build.

## 1.6.3 - 2026-07-24

Prompt-editor polling fix and paired cloud artifacts.

- Preserved the prompt editor and its unsaved draft while same-project detail or project-list polling refreshes the current project.
- Kept project and target-language switches authoritative: changing either still exits the old edit scope and loads the new prompt.
- Added deterministic browser coverage for both detail polling and focus-triggered project-list refreshes.
- Standardized the account-enabled universal artifact name as `有账号-v1.6.3.zip` and shipped it beside the dedicated `无账号-v1.6.3.zip` cloud-off artifact.

## 1.6.2 - 2026-07-23

Cloud no-account and official sentence-template release.

- Added the production `cloud/off` runtime profile for trusted intranet deployments that need the online workbench without login, registration, user, role, or project-member administration.
- Added a dedicated no-account release artifact locked to `cloud/off`, with external data/settings requirements, no administrator bootstrap credentials, and profile-aware package readback checks.
- Kept `cloud/required` as the default cloud profile and preserved the authenticated account, role, membership, and self-registration behavior in the universal build.
- Integrated official sentence-template extraction, placeholder-safe sentence adaptation, and translation consistency warnings into announcement terminology preparation and delivery.
- Extended source and extracted-package checks for cloud safeguards, nickname attribution, settings write protection, anonymous API access, and disabled account endpoints.

## 1.6.1 - 2026-07-21

Unified runtime-profile release.

- Converged the product on one source line, one commit, one production frontend build, and one universal release archive for both supported production profiles.
- Defined `local/off` for local sign-in-free operation and `cloud/required` for authenticated online operation; `cloud/off` now fails closed as an invalid configuration.
- Kept authentication-off behavior explicit: a synthetic local administrator owns operations while login, registration, user management, and project-member management are hidden. Authentication-required mode retains login, roles, membership, and self-registration.
- Made profile transitions non-destructive for projects, business data, and files, while clearing incompatible server and browser sessions so old sessions cannot revive after a mode switch.
- Added explicit Windows and Linux launch profiles plus dual source E2E and extracted-package smoke gates that verify both profiles against the same manifest version, Git SHA, frontend digest, and runtime payload digest.

## 1.6.0 - 2026-07-20

Account self-registration release.

- Added public self-registration for account-enabled deployments. Anonymous visitors see only the login and registration screens; successful registrations create active `member` accounts without granting project membership automatically.
- Stabilized login/registration transitions by canceling stale authentication requests and making successful login responses self-contained.
- Expanded administrator user management with registration and last-login metadata, deterministic newest-first ordering, and independent loading states for list refreshes and account actions.
- Kept existing users, projects, and data compatible without migration. This was the pre-unification account-line candidate and is superseded by v1.6.1's single-version, dual-profile model.
- Documented fresh-directory deployment with external `LWS_DATA_ROOT` and `settings.local.json`, manifest-derived `LWS_GIT_SHA`, one worker, and an atomic `current` switch.

## 1.5.3 - 2026-07-17

Account acceptance and deployment hygiene release.

- Hid the legacy browser nickname control when authenticated accounts are enabled and added a real loading state to project membership management.
- Rejected disabled/admin membership targets, current-password reuse, and usernames that cannot later pass the login schema.
- Revoked existing sessions after role changes or administrator CLI resets/promotions, and disabled self-demotion/self-disable controls in the user management UI.
- Added browser and backend regression coverage for the affected account flows and documented fresh-directory deployment requirements.

## 1.5.1 - 2026-07-16

Project-selection race fix release.

- Prevented an older project-list refresh from overriding the project selected by a newer refresh, including immediately after creating a project.
- Added deterministic browser regression coverage for the overlapping polling/create response order.

## 1.5.0 - 2026-07-16

Account permissions and combined workbench lifecycle release.

- Added server-side login sessions, argon2id password hashing, forced first-login password changes, login abuse protection, and fail-closed cloud authentication.
- Added global `admin` / `ops` / `member` roles, per-project membership, centrally declared route capabilities, admin user management, project member management, and permission-aware frontend controls.
- Consolidated formal translation, quick task, and announcement lifecycles so completed work starts from a clean task while running work resumes the exact task; historical deliveries remain view-only.
- Hardened glossary and translation-archive imports with preview/commit semantics, deterministic replacement rules, rollback support, and preserved archive lookup as a soft reference for quick tasks and announcements without writing those results back.
- Integrated Vietnamese as internal language code `VN`, removed the obsolete `EN2` input, and fixed quick-task result isolation across tasks and languages.
- Kept the persistent dual-lane queue, restart recovery, queue visibility, Git/static-asset deployment checks, and release archive verification while extending deployment checks and stability smoke tests to authenticated cloud installations.

## 1.4.0 - 2026-07-15

Persistent dual-lane queue and shared-workbench reliability release.

- Added two durable FIFO channels: one global formal language-table worker and one global quick-task/announcement worker. The two channels may run concurrently for the same project while each channel remains strictly serial.
- Added restart recovery, queue-level cancellation audit, operator/position visibility, dual-lane queue APIs, and queue-authoritative header/project badges. Running work pauses for explicit continuation after restart; waiting work resumes automatically.
- Fixed orphaned legacy QA cleanup, created-to-queued state ordering, line-proofread Chinese status text, queue/handler race conditions, and graceful single-worker shutdown.
- Quick tasks and announcements still generate downloadable outputs but no longer write project translation archives; formal language-table QA/delivery continues to archive normally.
- Release packaging now emits and verifies a `.zip.sha256` sidecar in addition to the archive's internal member checksum manifest.

## 1.3.4 - 2026-07-15

Unicode operator nickname compatibility release.

- Operator nicknames are now percent-encoded before being attached to browser API requests, so Chinese and other non-Latin nicknames no longer trigger the browser `Headers` ISO-8859-1 error.
- The backend decodes the transport-safe nickname before attribution, preserving the original nickname in events, active-job ownership, and conflict messages.
- Added backend and browser regression coverage for a Chinese nickname creating an API-backed project/run.
- Deployment guidance now requires a fresh release directory and atomic switch instead of overlaying new files onto an old frontend build.

## 1.3.3 - 2026-07-14

Shared-workbench operator attribution release.

- Added an always-visible operator nickname control independent of the hidden online settings page; the nickname remains browser-local and is sent with API requests through `X-Operator`.
- Cloud deployments now require a nickname before background translation, QA, model-fix, announcement, or multilingual AI work can start or resume, and reject the request before changing task state.
- Background job leases persist the initiating operator. Active-job panels and same-project conflict messages now show who owns the running task, with a clear fallback for older unsigned leases.
- Added direct “设置昵称” recovery from blocked workflow status messages and responsive desktop/narrow-screen coverage for the new control.

## 1.3.2 - 2026-07-14

Production deployment reliability release.

- Added installable single-node systemd and Nginx templates with same-origin routing, production cache headers, large-upload handling, and a release-independent persistent data directory.
- Deployment checks now reject Vite development pages, stale HTML/API cache policy, Git/version mismatches, missing public assets, and any mismatch between public HTML, backend asset metadata, and the packaged frontend build.
- Full-page refresh restores the current project and all workbench views while project, run, artifact, and settings data continue to reload from the API.
- Release packaging now uses a production allowlist, excludes private/runtime material, scans source and archive text for credentials, and verifies every archive member and checksum after writing.

## 1.3.1 - 2026-07-12

Background-task model for QA and removal of the global busy lock — the three items deferred from the 2026-07-11 UX audit.

- QA now runs as a background job: new `POST /api/runs/{id}/qa/start` (shares the per-project job lease with translation/model-fix) and `POST /api/runs/{id}/qa/cancel` (cancels at the next pipeline stage boundary; no partial results are written). Direct QA, quick-task proofreading, and the manual-fix QA rerun (new `POST /api/runs/{id}/manual-fixes/start`) all use it; the QA step shows a live running state with a "取消 QA" button. Canceling a multilingual QA queue now also stops the in-flight language's QA at the next stage boundary.
- Long-running background tasks (translation, QA, model fixes) no longer hold the global `busy` lock, so unrelated buttons (glossary edits, other tabs, delivery) stay usable while a task runs. `busy` only covers short in-flight requests; start buttons guard themselves with their own run state and true conflicts are rejected by the backend lease with a 409 plus the "查看活跃任务" affordance.
- When a run reaches a terminal state, the project list refreshes immediately (sidebar badges no longer lag up to 10s behind the run detail).
- Repo-layout guard tests in `test_risk_hardening.py` are now anchored to the repo root, so the backend suite passes from both `backend/` and the repo root.

## 1.3.0 - 2026-07-11

Workbench UI redesign (light "Sites" theme) plus a full user-perspective UX audit with two fix batches. Audit evidence lives in `docs/superpowers/reports/ux-full-audit-2026-07-11.md` and `docs/superpowers/reports/product-design-audit-2026-07-11/`.

UI redesign and QA delivery hardening:

- Rebuilt the workbench visual language on a light theme: compact project sidebar, phase-grouped 9-step wizard navigation, denser overview/asset tables, sticky headers, and responsive layouts down to mobile widths; QA rule codes now map to Chinese labels and issue-delivery outcomes were simplified.
- Announcement flow: zero extracted terms no longer blocks the lookup step; delivery packages now write back to the project translation archive (including issue deliveries, tagged with their origin).
- English punctuation normalization no longer breaks times/ratios/URLs (`10:00` stays `10:00`).

Hard blockers found by the audit, fixed:

- Confirming glossary candidates 500'd when one source row produced multiple terms (duplicate `term_key` hit the unique index); duplicates now merge/degrade safely, with regression coverage.
- Bare 500 responses are no longer misreported as "连接工作台后端失败"; only proxy failures/empty replies suggest restarting the workbench.
- Wizard steps 2 (AI analysis) and 4 (language table) can no longer be skipped silently: advancing without prerequisites asks for confirmation, step 5/7 dead-ends gained "返回判定输入" jump buttons, and the step navigation itself now disables steps whose prerequisites are missing (same for the quick-task 3-step nav).

UX smoothness batch:

- Pause button binds to the translation run being viewed, not the globally-latest run (multilingual queues could cancel the wrong task).
- Re-entry locks on formal translation / multilingual queue / quick-task start close the slow-network double-submit window.
- Silent failures now surface in the status bar: language-table readiness checks, manual glossary add/edit/delete, project meta saves (which also keep the editor open so drafts survive), deliverables loading (with a retry button).
- Status-bar messages are dismissable; run-progress polling that fails 5 times in a row unlocks the UI instead of freezing it; quick-task TXT results show a clear error instead of "正在读取结果..." forever.
- Polish: scroll position resets on project/tab/step switches, inline validation in the new-project modal, grayscale styling for disabled buttons, "仅显示前 20 条" label on glossary previews, pagination for 50+ row announcement temp glossaries, local-timezone generated dates, quick-task paste field contrast fix.

## 1.2.0 - 2026-07-09

Translation-archive lookup in the formal translation flow, and an opt-in in-product line-by-line AI proofreading pass. Planned in `docs/superpowers` plan "译文归档注入与逐行校对".

Archive lookup injection (P1):

- Formal translation workpack rows now carry `reference_hits` looked up from the project's translation archive (QA-passed/imported/manual entries), the same way quick tasks already did; the batch prompt's existing Archive rule now actually receives data in formal runs. The lookup helper is shared (`reference_lookup.attach_reference_hits`) and quick tasks reuse it.
- Run metadata records a `reference_audit` (archive entries, hit rows, total hits) and the event stream logs one summary line per run.
- The first lookup is frozen into a run-scoped `reference_hits_snapshot.json` (same pattern as glossary/prompt snapshots): a passed run imports its own rows into the archive, so a live lookup on resume would change the batch fingerprint and wipe the resume cache. New runs pick up the grown archive; resumed runs keep their original hits.
- Known effect: batch fingerprints of *new* runs differ from pre-1.2.0 manifests once the archive has data (expected; resume caches of in-flight runs are protected by the snapshot).

In-product line proofreading (P2, opt-in):

- `TranslateRequest`/`MultilingualQueueRequest` gained `enable_line_proofread: bool = false`. Default off, matching the collaboration rule that deep per-line proofreading only runs when explicitly requested; the multilingual queue passes the flag through to child runs.
- New `backend/app/workflow/line_proofread.py`: after machine QA passes/fails, the model reviews the QA workbook in ~50-row batches (source + current target + term_hits) and returns strict-JSON suggestions; a deterministic audit gate rejects suggestions that lose protected tokens (placeholders/tags/escaped newlines), drift from term_hits targets, drop numbers, or change nothing. Accepted fixes are applied to a copy via the shared workbook-fix path and machine QA is re-run on the result; the run's final status comes from that second QA pass.
- Artifacts: audited suggestions land in a `line_proofread_suggestions` JSONL artifact (internal, not a delivery file); run metadata records `line_proofread: {reviewed_rows, batches, suggested, rejected_by_audit, applied}`.
- Frontend: Step 7 gained a "深度逐行校对" checkbox (default unchecked, with a time-cost hint) and shows the proofread summary after the run; RunDetail shows the same summary line; copy lives in `uiText.ts`.
- With the test-fake provider the reviewer deterministically suggests nothing, so dev/e2e flows exercise the full pipeline without a real key; real providers reuse the existing keyless-run preflight block.

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
