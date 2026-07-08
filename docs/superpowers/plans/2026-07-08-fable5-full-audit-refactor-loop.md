# Fable5 Full Audit And Refactor Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to execute this loop. If the worker can spawn independent workers, use superpowers:subagent-driven-development for audit subpasses, but the main worker remains responsible for git state, final verification, and commits. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use Fable5 only as the architecture governor for Localization Workflow Studio while cheaper models do bulk reading, tests, mechanical edits, and verification, then keep looping until the completion criteria are met or a real blocker is reached.

**Architecture:** This is a model-budgeted, verification-driven loop, not a rewrite instruction. Cheaper executor models gather evidence, run tests, draft reports, and implement scoped batches. Fable5 is invoked only at explicit architecture checkpoints: choosing Module seams, approving important reorganization, reviewing cross-cutting workflow changes, and final sign-off.

**Tech Stack:** FastAPI, SQLite, Python 3.11+, pytest, Ruff, compileall, React 19, TypeScript, Vite, Playwright, PowerShell on Windows, optional Bash for `start-lws.sh` syntax checks.

---

## Non-Negotiable Rules

1. Work in `D:\codex\localization-workflow-studio`.
2. Do not delete, overwrite, or stage unrelated untracked files, especially `docs/superpowers/plans/2026-07-07-large-text-workbench-productization.md`.
3. Do not commit secrets, real workbooks, `settings.local.json`, SQLite databases, upload/run/project/artifact data, logs, `.venv`, `node_modules`, `.pytest_cache`, `.ruff_cache`, or `__pycache__`.
4. Do not replace working product flows with a simplified implementation.
5. Do not remove tests to make verification pass.
6. Do not do a full visual redesign while fixing workflow reliability.
7. Do not report success unless the required validation tier passed after the final code change.
8. If the same command or approach fails twice, stop that path, record the blocker, and switch to a narrower fix or ask for help.
9. Do not use Fable5 for bulk file reading, `rg`, line counting, dependency checks, formatting, simple test writing, command execution, or mechanical patching.
10. Do not let a cheaper model redesign Module Interfaces, move workflow ownership, change DB/runtime contracts, or decide release readiness without a Fable5 checkpoint.

## Model Budget And Dispatch Policy

Use three roles:

```text
Fable5 Architect:
- Owns architecture direction, Module seam decisions, important reorganization, risky cross-flow changes, and final acceptance.
- Reads short briefs and selected snippets, not the whole repo.
- Must approve changes that alter formal translation evidence, QA semantics, delivery semantics, provider readiness, large-text gates, artifact contracts, or release/package rules.

Executor Model:
- Use a cheaper capable model such as Sonnet 5, GPT-5.x mini, or any local default Cursor model.
- Owns bulk reading, source maps, grep scans, test drafting, mechanical refactors behind approved Interfaces, docs updates, command execution, validation log updates, and commits.
- Must prepare a short architecture brief before asking Fable5 to decide.

Validator Model:
- Can be the same cheaper model unless the diff is cross-cutting.
- Owns diff review, validation-output triage, regression-risk check, and completion checklist maintenance.
```

Default to the Executor Model. Escalate to Fable5 only when one of these triggers is true:

```text
- A Module Interface is being created, removed, renamed, or made cross-cutting.
- The change touches two or more major workflows: translation, QA, delivery, glossary, announcement, quick task, project management, deployment.
- The change can affect formal translation evidence, direct QA evidence, hard-block recovery, delivery downloads, provider/API-key handling, generated artifacts, package cleanliness, or cloud/local mode.
- The large-text productization plan needs a scope decision or parity decision against workflow/localization/utils/large_text_multilingual_gate.py.
- A cheaper model proposes deleting code, migrating data, changing DB schema, broadening dependencies, or replacing an existing workflow.
- Two executor attempts fail or the same validation class fails twice.
- Final completion or release/package readiness is being declared.
```

Never escalate to Fable5 for:

```text
- Running shell commands.
- Reading every file in a directory.
- Producing line-count tables.
- Adding straightforward regression tests once behaviour is known.
- Applying a patch that follows an already approved Interface.
- Updating reports, logs, markdown checklists, or validation tables.
- Fixing lint, formatting, import order, or obvious type errors caused by the current batch.
```

Every Fable5 call must be preceded by a compact handoff packet:

```markdown
## Fable5 Architecture Checkpoint

- Decision needed:
- Current batch:
- Product invariant at risk:
- Files involved:
- Existing tests:
- Proposed Module / Interface:
- Alternatives considered:
- Executor recommendation:
- Exact question for Fable5:
```

Record every model handoff in:

```text
docs/superpowers/reports/model-dispatch-log.md
```

The dispatch log format:

```markdown
# Model Dispatch Log

| Time | Role | Model | Scope | Input Size | Decision/Output | Follow-up |
|---|---|---|---|---|---|---|
```

## Required Start Command

Open Cursor in the repo root. Start with a cheaper Executor Model and give it this exact instruction:

```text
Read docs/superpowers/plans/2026-07-08-fable5-full-audit-refactor-loop.md completely. Execute it from Task 0 onward as the Executor Model. Do not use Fable5 for bulk reading or mechanical execution. Prepare Fable5 Architecture Checkpoints only when the dispatch policy says escalation is required. Keep looping until every Completion Criteria checkbox is true, or until you hit a blocker that repeats twice. Do not skip context ingestion. Do not make broad rewrites. Commit only verified, scoped batches.
```

## Files And Areas To Read First

The worker must read these before editing:

```text
AGENTS.md
README.md
README.zh-CN.md
VERSION
pyproject.toml
pytest.ini
frontend/package.json
docs/QUALITY_GATES.md
docs/STABILITY_TEST_LIST.md
docs/optimization/validation_set/README.md
docs/optimization/failure_log.md
docs/optimization/improvement_backlog.md
docs/superpowers/plans/2026-07-07-large-text-workbench-productization.md
backend/app/main.py
backend/app/errors.py
backend/app/config.py
backend/app/db.py
backend/app/jobs.py
backend/app/download_urls.py
backend/app/delivery_naming.py
backend/app/providers.py
backend/app/schemas.py
backend/app/translation_batches.py
backend/app/routers/api.py
backend/app/routers/artifacts.py
backend/app/routers/delivery.py
backend/app/routers/glossary.py
backend/app/routers/projects.py
backend/app/routers/qa.py
backend/app/routers/runs.py
backend/app/routers/shared.py
backend/app/routers/system.py
backend/app/routers/translations.py
backend/app/workflow/translation.py
backend/app/workflow/translation_orchestrator.py
backend/app/workflow/multilingual.py
backend/app/workflow/qa.py
backend/app/workflow/semantic_qa.py
backend/app/workflow/delivery.py
backend/app/workflow/glossary.py
backend/app/workflow/announcement.py
backend/app/workflow/announcement_ai.py
backend/app/workflow/asset_import_export.py
backend/app/workflow/project_analysis.py
workflow/localization/utils/large_text_multilingual_gate.py
workflow/localization/utils/large_text_multilingual_runner.py
workflow/localization/utils/large_text_multilingual_retro.py
workflow/localization/utils/quality_harness.py
workflow/localization/utils/translation_harness.py
workflow/glossary/scripts/extract_glossary.py
frontend/src/main.tsx
frontend/src/apiClient.ts
frontend/src/types.ts
frontend/src/SettingsModal.tsx
frontend/src/components/translationWizard/TranslationWizard.tsx
frontend/src/components/announcement/AnnouncementWorkflow.tsx
frontend/src/components/assets/ProjectAssetTabs.tsx
frontend/src/components/project/ProjectMeta.tsx
frontend/src/components/quickTask/QuickTaskWizard.tsx
frontend/src/components/shared/WorkflowPrimitives.tsx
frontend/src/styles.css
frontend/e2e/studio-ui-flow.spec.ts
frontend/e2e/manual-fix-flow.spec.ts
scripts/deployment_check.py
scripts/stability_check.py
scripts/build_release_package.py
start-lws.sh
start-workbench.cmd
```

If `CONTEXT.md` or `docs/adr/` exists, read them before architectural changes. If they do not exist, create `CONTEXT.md` only after Task 2 identifies the stable domain vocabulary.

## Output Files The Loop Must Maintain

Create and keep these files current during the loop:

```text
docs/superpowers/reports/fable5-loop-state.md
docs/superpowers/reports/fable5-audit-report.md
docs/superpowers/reports/fable5-validation-log.md
docs/superpowers/reports/model-dispatch-log.md
CONTEXT.md
```

`CONTEXT.md` must stay short. It defines domain terms, not implementation notes.

---

## Task 0: Guard The Working Tree

**Files:**
- Create: `docs/superpowers/reports/fable5-loop-state.md`
- Create: `docs/superpowers/reports/model-dispatch-log.md`
- No code files modified

- [ ] **Step 0.1: Confirm repo and git state**

Run:

```powershell
cd D:\codex\localization-workflow-studio
git status --short --branch
git rev-parse --short HEAD
git log -1 --oneline
```

Expected current baseline:

```text
## master...origin/master
?? docs/superpowers/plans/2026-07-07-large-text-workbench-productization.md
1d30ff6
1d30ff6 chore: update 1.0.3 repo metadata
```

If the branch or untracked files differ, record the difference in `docs/superpowers/reports/fable5-loop-state.md` before continuing.

- [ ] **Step 0.2: Create a working branch**

Run:

```powershell
git switch -c codex/fable5-full-audit-refactor
```

If the branch already exists:

```powershell
git switch codex/fable5-full-audit-refactor
```

- [ ] **Step 0.3: Create report directory**

Run:

```powershell
New-Item -ItemType Directory -Force docs\superpowers\reports
```

- [ ] **Step 0.4: Write initial loop state**

Create `docs/superpowers/reports/fable5-loop-state.md` with this content and then update it throughout the loop:

```markdown
# Fable5 Loop State

## Baseline

- Repo: D:\codex\localization-workflow-studio
- Branch:
- HEAD:
- Started:
- Initial untracked files:

## Current Phase

- Phase: Task 1 context ingestion
- Current item:
- Last validation tier:
- Last validation result:
- Active model role:
- Last Fable5 checkpoint:

## Batch Log

| Batch | Scope | Files | Validation | Commit | Result |
|---|---|---|---|---|---|

## Blockers

| Time | Command/Action | Failure | Attempts | Next Decision |
|---|---|---|---|---|

## Model Budget Notes

- Default executor model:
- Fable5 used for:
- Fable5 avoided for:
```

Do not commit yet.

- [ ] **Step 0.5: Write model dispatch log**

Create `docs/superpowers/reports/model-dispatch-log.md`:

```markdown
# Model Dispatch Log

| Time | Role | Model | Scope | Input Size | Decision/Output | Follow-up |
|---|---|---|---|---|---|---|
```

---

## Task 1: Full Context Ingestion

**Files:**
- Modify: `docs/superpowers/reports/fable5-loop-state.md`
- Create: `docs/superpowers/reports/fable5-audit-report.md`

- [ ] **Step 1.1: Read the required file set**

Use the Executor Model for this step. Use Cursor file reads and terminal commands. Do not rely on memory or chat summaries. Do not use Fable5 for this bulk read.

Run:

```powershell
rg --files | rg "^(backend|frontend|workflow|docs|scripts)|^(AGENTS|README|VERSION|pyproject|pytest|start)"
```

Then read every file listed in the "Files And Areas To Read First" section of this plan.

- [ ] **Step 1.2: Build a live source map**

Run:

```powershell
$files = Get-ChildItem -LiteralPath backend,workflow,frontend\src -Recurse -File -Include *.py,*.tsx,*.ts -ErrorAction SilentlyContinue
$results = foreach ($f in $files) { $n=(Get-Content -LiteralPath $f.FullName -ErrorAction SilentlyContinue | Measure-Object -Line).Lines; [pscustomobject]@{Lines=$n; Path=$f.FullName} }
$results | Sort-Object Lines -Descending | Select-Object -First 40 | Format-Table -AutoSize
```

Record the top files in `fable5-audit-report.md`.

- [ ] **Step 1.3: Record the product invariants**

Add this section to `docs/superpowers/reports/fable5-audit-report.md`:

```markdown
# Fable5 Audit Report

## Product Invariants

- Formal Studio translation requires the same run to produce prompt snapshot, workpack, model response, validated workbook, and final QA report.
- Direct QA runs are valid QA evidence but do not prove Studio performed translation.
- Test fake provider is for CI/no-key regression only; formal project translation must be blocked when no formal provider key exists.
- Hard block must not be a dead end: users must be able to inspect issues, download issue artifacts, apply fixes, rerun QA, or produce explicitly risky issue delivery.
- Delivery surfaces must show only real downloadable final artifacts.
- Online/current deployment validation requires more than `/api/health`; `/api/version` and frontend/backend version match matter.
- Generated artifacts and metadata must not contain API keys.
```

- [ ] **Step 1.4: Fable5 checkpoint only if invariants conflict**

Do not call Fable5 if the executor only recorded known invariants. Call Fable5 only if the executor finds a contradiction between docs, code, and tests that affects architecture direction.

If escalation is needed, write a Fable5 Architecture Checkpoint in `model-dispatch-log.md`, ask Fable5 the exact question, and record the answer in `fable5-audit-report.md`.

- [ ] **Step 1.5: Commit the report scaffold**

Run:

```powershell
git add docs/superpowers/reports/fable5-loop-state.md docs/superpowers/reports/fable5-audit-report.md docs/superpowers/reports/model-dispatch-log.md
git commit -m "docs: start fable5 audit loop state"
```

---

## Task 2: Audit Before Refactor

**Files:**
- Modify: `docs/superpowers/reports/fable5-audit-report.md`
- Modify: `docs/superpowers/reports/model-dispatch-log.md`
- Create or modify: `CONTEXT.md`

- [ ] **Step 2.1: Audit P0 user-facing failures**

Inspect the code paths behind these backlog items:

```text
I-001 upload errors show user-readable messages
I-002 frontend must not expose traceback, command, or server paths
I-003 delivery page shows only real downloadable artifacts
I-004 full language table import is not mistaken for project glossary
I-005 glossary import state refreshes from actual stored rows
I-006 announcement completed state differs from new task entry
I-007 hard block recovery path is standardized
I-008 online version consistency is visible/checkable
I-009 project deletion refreshes list and selected project
I-010 AI flows check provider before creating formal runs
```

For each item, record:

```markdown
### I-00X Title

- Files:
- Current behaviour:
- Risk:
- Existing tests:
- Missing tests:
- Recommended fix:
- Validation:
- Priority:
```

- [ ] **Step 2.2: Audit architectural friction**

Use these architecture terms exactly:

```text
Module
Interface
Implementation
Depth
Seam
Adapter
Leverage
Locality
```

Record at least these Module candidates:

```markdown
## Module Deepening Candidates

### Candidate A: User-facing error Module
- Files:
- Problem:
- Solution:
- Benefits:
- Tests:

### Candidate B: Delivery artifact Module
- Files:
- Problem:
- Solution:
- Benefits:
- Tests:

### Candidate C: Provider readiness Module
- Files:
- Problem:
- Solution:
- Benefits:
- Tests:

### Candidate D: Full language table classification Module
- Files:
- Problem:
- Solution:
- Benefits:
- Tests:

### Candidate E: Large text product gate Module
- Files:
- Problem:
- Solution:
- Benefits:
- Tests:

### Candidate F: Frontend workflow state Module
- Files:
- Problem:
- Solution:
- Benefits:
- Tests:
```

Do not design new Interfaces yet. Only identify the friction, locality problem, leverage gain, and tests. Use the Executor Model for this pass.

- [ ] **Step 2.3: Create or update domain vocabulary**

If `CONTEXT.md` does not exist, create it:

```markdown
# Localization Workflow Studio Context

## Domain Terms

- Project: A local work area that owns source materials, glossary data, language tables, runs, artifacts, and delivery outputs.
- Run: A resumable execution record for translation, QA, announcement, quick task, import, or delivery work.
- Artifact: A stored file produced or uploaded during a project or run, with metadata that lets the UI display or download it safely.
- Formal Translation: A Studio translation run that produced prompt snapshot, workpack, provider response, validated workbook, and final QA report for the same run.
- Direct QA: A QA run against an uploaded translated workbook. It is QA evidence, not formal translation evidence.
- Hard Block: A QA or gate failure that prevents clean final delivery but still must offer inspection, repair, rerun, or explicit issue-delivery paths.
- Large Text Pack: A language-table workload whose rows, target-language count, workbook count, or estimated target cells require deterministic gates beyond normal QA.
- Delivery Readback: A post-generation check that reads the final output file and verifies target columns and non-empty target cells before exposing downloads.

## Architecture Terms

- Module: Anything with an Interface and an Implementation.
- Interface: Everything a caller must know to use the Module.
- Implementation: The code inside the Module.
- Depth: Leverage at the Interface.
- Seam: Where an Interface lives.
- Adapter: A concrete thing satisfying an Interface at a Seam.
- Leverage: What callers get from Depth.
- Locality: What maintainers get when change and bugs are concentrated.
```

- [ ] **Step 2.4: Fable5 architecture checkpoint**

Now use Fable5 once. Do not paste the whole repo. Give Fable5 only:

```text
- Product Invariants
- P0 user-facing failure audit summary
- Module Deepening Candidates
- CONTEXT.md
- The current git status
```

Ask:

```text
Which Module deepening candidates should be approved for implementation, which should be deferred, and which require narrower Interfaces before executor implementation? Return only decisions, rationale, and required validation.
```

Record the result in:

```text
docs/superpowers/reports/fable5-audit-report.md
docs/superpowers/reports/model-dispatch-log.md
```

- [ ] **Step 2.5: Commit the audit**

Run:

```powershell
git add docs/superpowers/reports/fable5-audit-report.md docs/superpowers/reports/model-dispatch-log.md CONTEXT.md
git commit -m "docs: audit workbench refactor candidates"
```

---

## Task 3: Main Work Loop

Repeat this task until all P0 items are fixed, all selected P1/P2 refactors are done, and the Completion Criteria pass.

**Files:**
- Modify only files required by the selected item
- Modify: `docs/superpowers/reports/fable5-loop-state.md`
- Modify when a failure or improvement is found: `docs/optimization/failure_log.md`
- Modify when a durable improvement is adopted: `docs/optimization/improvement_backlog.md`
- Modify when a user path changes: relevant validation case under `docs/optimization/validation_set/cases/`

## Batch Selection Order

Always pick the highest priority unfinished item in this order:

1. I-002 user-facing error safety.
2. I-001 upload error clarity.
3. I-003 delivery artifact existence and Not Found prevention.
4. I-010 provider readiness before formal AI runs.
5. I-007 hard block recovery.
6. I-004 full language table classification.
7. I-005 glossary import readback/refresh.
8. I-008 version consistency.
9. I-009 project deletion recovery.
10. I-006 announcement completed/new-task split.
11. Large text productization from `docs/superpowers/plans/2026-07-07-large-text-workbench-productization.md`.
12. Backend Module deepening from Task 2.
13. Frontend workflow state Module deepening from Task 2.

## Required Cycle For Each Batch

- [ ] **Step 3.1: Define the batch**

Update `fable5-loop-state.md`:

```markdown
## Current Phase

- Phase: batch
- Current item: I-00X / Candidate X
- Files planned:
- Expected focused tests:
- Expected validation tier:
- Executor model:
- Requires Fable5 before implementation: yes/no
- Fable5 reason:
```

- [ ] **Step 3.1a: Choose model role**

Use the Executor Model unless the selected batch matches an escalation trigger in the Model Budget And Dispatch Policy.

Fable5 is required before implementation for these batch classes:

```text
- Candidate A-F Interface design.
- Large text product gate Interface or parity decisions.
- Formal translation evidence changes.
- Hard-block semantics changes.
- Delivery artifact contract changes.
- Provider readiness contract changes.
- Cross-flow frontend state redesign.
```

Fable5 is not required before implementation for:

```text
- Adding focused regression tests from already approved behaviour.
- Fixing a localized bug behind an existing Interface.
- Updating reports, validation cases, or backlog status.
- Running validation and triaging ordinary failures.
```

If Fable5 is required, prepare the compact Fable5 Architecture Checkpoint packet, get the decision, record it in `model-dispatch-log.md`, and only then implement.

- [ ] **Step 3.2: Write or identify a failing test**

Before implementation, add a focused failing test when practical.

Use backend tests for backend changes:

```powershell
python -m pytest backend/tests/test_risk_hardening.py -q
python -m pytest backend/tests/test_workflow_e2e.py -q
```

Use workflow harness tests for local workflow changes:

```powershell
python -m pytest workflow/localization/tests/test_large_text_multilingual_gate.py -q
python -m pytest workflow/glossary/tests/test_extract_glossary_workflow.py -q
```

Use frontend tests for UI flow changes:

```powershell
npm --prefix frontend run build
npm --prefix frontend run e2e -- --workers=1
```

If a failing automated test is not practical, record the manual validation case and why an automated test is not practical in `fable5-audit-report.md`.

- [ ] **Step 3.3: Implement the smallest change**

Rules:

```text
- Change only the selected batch files.
- Prefer a deep Module behind a small Interface over scattered conditionals.
- If only one caller exists, do not invent a broad Adapter unless it removes real complexity.
- Keep product routes and user workflows stable unless the batch explicitly changes them.
- Do not mix formatting-only changes with behavioural changes.
```

- [ ] **Step 3.4: Run focused verification**

Run the smallest relevant command first.

Examples:

```powershell
python -m pytest backend/tests/test_risk_hardening.py -q
python -m pytest backend/tests/test_workflow_e2e.py -q
python -m pytest workflow/localization/tests/test_large_text_multilingual_gate.py -q
npm --prefix frontend run build
npm --prefix frontend run e2e -- --workers=1
```

- [ ] **Step 3.5: Run batch verification tier**

Use the validation tiers below. Do not commit until the selected tier passes.

- [ ] **Step 3.5a: Fable5 review only for risky diffs**

After verification, call Fable5 for review only if the actual diff changed an approved Module Interface, workflow semantics, artifact contract, provider contract, release/package rule, or large-text gate behaviour.

Do not call Fable5 for ordinary green executor batches.

- [ ] **Step 3.6: Update loop reports**

Update `fable5-loop-state.md` with:

```markdown
| Batch | Scope | Files | Validation | Commit | Result |
|---|---|---|---|---|---|
```

If a real product failure was found, update `docs/optimization/failure_log.md`.

If an improvement was adopted, update `docs/optimization/improvement_backlog.md` status.

Update `docs/superpowers/reports/model-dispatch-log.md` if any Fable5 or validator handoff occurred.

- [ ] **Step 3.7: Commit verified batch**

Run:

```powershell
git status --short
git add docs/superpowers/reports/fable5-loop-state.md
git diff --cached --check
git commit -m "<type>: <scoped description>"
```

For real batches, replace the `git add` command with the exact files changed in that batch. Never use `git add .`.

Use commit types:

```text
test:
fix:
feat:
refactor:
docs:
chore:
```

Do not stage unrelated untracked files.

---

## Validation Tiers

## Tier A: Every Code Batch

Run after any Python code change:

```powershell
python -m compileall -q backend workflow scripts
python -m ruff check backend/app backend/tests scripts --select E9,F
```

Run after any frontend code change:

```powershell
npm --prefix frontend run build
```

## Tier B: Workflow Batch

Run when a batch touches translation, QA, delivery, provider, artifacts, glossary, announcement, or project state:

```powershell
python -m pytest backend/tests/test_risk_hardening.py backend/tests/test_workflow_e2e.py backend/tests/test_multilingual_orchestration.py backend/tests/test_multilingual_delivery.py -q
python -m pytest workflow/localization/tests workflow/glossary/tests -q
npm --prefix frontend run e2e -- --workers=1
```

## Tier C: Full Local Confidence

Run every three commits and before declaring completion:

```powershell
python -m compileall -q backend workflow scripts
python -m ruff check backend/app backend/tests scripts --select E9,F
python -m pytest -q
npm --prefix frontend run build
npm --prefix frontend run e2e -- --workers=1
```

## Tier D: Runtime And Deployment Confidence

Run before reporting final completion:

```powershell
python scripts\deployment_check.py --base-url http://127.0.0.1:5174 --expect-version (Get-Content VERSION)
python scripts\stability_check.py --base-url http://127.0.0.1:5174
```

If local services are not running, start them only after checking port ownership. Do not kill unrelated processes.

Port check:

```powershell
Get-NetTCPConnection -LocalPort 8000,5173,5174 -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,State,OwningProcess
```

## Tier E: Package Confidence

Run only if packaging or deployment files changed:

```powershell
python scripts\build_release_package.py
```

Then inspect the built package member list and manifest. Required exclusions:

```text
.git
.venv
node_modules
settings.local.json
lws-data
*.sqlite
*.db
uploads
runs
projects
artifacts
logs
```

---

## Manual Validation Set

Before final completion, run or explicitly review these cases:

```text
001 new translation task: empty target language table to delivery
002 existing translated workbook direct QA
003 full language table glossary candidate generation
004 multilingual archive import/export
005 quick task translation
006 announcement TXT to delivery
007 hard block recovery
008 online/local smoke: version, health, upload, download, deletion
```

For each case, record in `docs/superpowers/reports/fable5-validation-log.md`:

```markdown
## Case 00X

- Date:
- Environment:
- Commit:
- Steps run:
- Result:
- Evidence:
- Follow-up:
```

---

## Completion Criteria

The loop is not complete until every item below is true:

- [ ] `docs/superpowers/reports/model-dispatch-log.md` shows Fable5 was used only for architecture checkpoints, risky diff review, or final acceptance.
- [ ] `docs/superpowers/reports/fable5-audit-report.md` covers all P0 backlog items and Module deepening candidates.
- [ ] `CONTEXT.md` exists and defines the domain terms used by the refactor.
- [ ] I-001 upload errors have user-readable handling or a documented blocker.
- [ ] I-002 traceback/raw command/server path exposure is blocked or a documented blocker exists.
- [ ] I-003 delivery surfaces show only real downloadable final artifacts or a documented blocker exists.
- [ ] I-010 provider readiness blocks formal AI runs without a configured formal provider or a documented blocker exists.
- [ ] I-007 hard block is not a dead end or a documented blocker exists.
- [ ] I-004/I-005 language table and glossary import behaviour are stable or documented blockers exist.
- [ ] Large text productization is either implemented and verified or explicitly deferred with a narrow reason in `fable5-audit-report.md`.
- [ ] Backend Module refactors preserve product behaviour and improve test locality.
- [ ] Frontend Module refactors preserve the existing user path and pass E2E.
- [ ] Tier C validation passed after the final code change.
- [ ] Tier D validation passed or the report clearly says local services were unavailable and lists exact next commands.
- [ ] Final Fable5 checkpoint reviewed only the compact final report, not the full repo.
- [ ] `git status --short --branch` is clean except intentionally untracked plan/report files.
- [ ] Final report distinguishes completed work, verified evidence, deferred items, and blockers.

---

## Final Report Template

When the loop is complete or blocked, write this to `docs/superpowers/reports/fable5-final-report.md`:

```markdown
# Fable5 Final Report

## Status

- Complete / Blocked:
- Branch:
- HEAD:
- Base:

## Completed

| Area | Change | Commit | Verification |
|---|---|---|---|

## Audit Findings

| Priority | Finding | Action |
|---|---|---|

## Validation

| Tier | Command | Result |
|---|---|---|

## Model Dispatch

| Role | Model | Scope | Result |
|---|---|---|---|

## Manual Cases

| Case | Result | Evidence |
|---|---|---|

## Deferred

| Item | Reason | Next step |
|---|---|---|

## Blockers

| Blocker | Evidence | Required help |
|---|---|---|
```

Commit the final report only if it reflects the real final state.
