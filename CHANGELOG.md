# Changelog

All notable changes are tracked here. The project uses semantic versioning while the public API is still pre-1.0.

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
