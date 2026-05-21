# Changelog

All notable changes are tracked here. The project uses semantic versioning while the public API is still pre-1.0.

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
