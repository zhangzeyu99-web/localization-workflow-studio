# Star Readiness v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Localization Workflow Studio easier for external GitHub users to understand, trust, try, and star.

**Architecture:** Keep the product code unchanged. Improve the public entry layer: README, getting-started guide, showcase, contribution policy, security policy, conduct policy, and GitHub repository metadata.

**Tech Stack:** Markdown documentation, GitHub repository settings, existing React/FastAPI/Vite/Python project.

---

### Task 1: Public Entry Rewrite

**Files:**
- Modify: `README.md`
- Create: `docs/GETTING_STARTED.md`
- Create: `docs/SHOWCASE.md`

- [ ] Replace the README first screen with an external-user pitch: problem, audience, demo, key capabilities, and quick start.
- [ ] Move setup detail into `docs/GETTING_STARTED.md` with exact PowerShell commands for backend, frontend, tests, and public sample data.
- [ ] Add `docs/SHOWCASE.md` with a fictional game-localization case using `examples/synthetic-language.xlsx`.

### Task 2: Community Trust Files

**Files:**
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`
- Create: `CODE_OF_CONDUCT.md`

- [ ] Add contribution scope, setup, validation commands, PR checklist, and data-safety rules.
- [ ] Add security policy for API keys, workbooks, SQLite data, and vulnerability reports.
- [ ] Add a concise code of conduct suitable for a small open-source workflow project.

### Task 3: GitHub Metadata

**Files:**
- No file changes.

- [ ] Set repository homepage to `https://zhangzeyu99-web.github.io/localization-workflow-studio/`.
- [ ] Replace the description with a concise external-facing pitch.
- [ ] Expand topics for discovery: `game-localization`, `l10n`, `translation-qa`, `excel`, `ai-assisted-translation`, `local-first`, `fastapi`, `react`, `vite`, `playwright`, `python`, `quality-gates`.

### Task 4: Verification and Publication

**Files:**
- All changed documentation files.

- [ ] Run a link/path sanity check over the new Markdown files.
- [ ] Run `npm run build` in `frontend`.
- [ ] Commit the branch, push it to origin, and open a pull request.
