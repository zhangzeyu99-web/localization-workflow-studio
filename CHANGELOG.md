# Changelog

All notable changes are tracked here. The project uses semantic versioning while the public API is still pre-1.0.

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
