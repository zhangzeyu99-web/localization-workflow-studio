# Roadmap

This roadmap keeps the public project focused: make the Studio easy to try, safe to run locally, and reliable enough for real localization delivery gates.

## v0.5.0 Public Ready

Goal: make the project understandable and useful to external users.

- Keep the README focused on the public demo, sample workbook, quick start, and safety boundary.
- Keep GitHub Pages available as a static, read-only product surface.
- Improve search and link previews with title, description, social metadata, robots, sitemap, and a social preview image.
- Keep examples synthetic and clearly separated from private runtime data.
- Reduce open PR noise, especially stale dependency PRs.
- Publish release notes for users, not internal implementation logs.

## v0.6.0 Real Delivery Workflow

Goal: make the real translation and QA delivery loop auditable end to end.

- Clearly distinguish a real provider translation run from an imported-workbook QA run.
- Complete the QA failure fix loop and `qa_changes` delivery artifacts.
- Keep provider keys and runtime artifacts outside the public repository.
- Document accepted input formats, generated artifacts, and quality gates.
- Preserve strict checks for IDs, placeholders, tags, line breaks, terminology, UI length, and input fingerprints.

## v1.0.0 Stable Workflow

Goal: publish a stable local-first workflow that teams can evaluate seriously.

- Keep backend, frontend, workflow core, and public documentation aligned.
- Provide a complete synthetic sample flow from workbook import to QA report and final workbook output.
- Keep CI green across backend, workflow, frontend build, and browser E2E.
- Treat major dependency and toolchain upgrades as deliberate maintenance releases.

## Out of Scope

- No real customer workbook data in the repository.
- No provider API keys in frontend code, GitHub Pages, screenshots, public issues, or docs.
- No mock output represented as production translation.
- No broad cloud product scope until the local-first workflow is stable.
