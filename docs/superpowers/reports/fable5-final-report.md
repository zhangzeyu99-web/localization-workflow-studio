# Fable5 Final Report

## Status

- Complete / Blocked: Complete
- Branch: codex/fable5-full-audit-refactor
- HEAD: 064d730 (final code change 68b77de; later commits are docs/reports)
- Base: master @ 1d30ff6

## Completed

| Area | Change | Commit | Verification |
|---|---|---|---|
| Reports scaffold | Loop state, dispatch log, audit report started | 811c204 | n/a (docs) |
| Audit | I-001..I-010 current-state audit, Module candidates A-F, Fable5 checkpoint decisions, CONTEXT.md | b0da28d | n/a (docs) |
| I-002 / Candidate A | App-level UserFacingError exception handler + status mapping in errors.py; cross-router no-leak regression tests; no router sites mass-edited | 7e006c5 | Tier A clean; risk-hardening 33; Tier B backend 137 |
| I-001 / I-003 / I-010 | Regression tests: unsupported-format 400 readability, deliverable disappears when file deleted on disk, keyless preflight parks run as needs_input with no provider call | b4aa443 | Tier A clean; 134 passed on touched files |
| I-007 / Candidate B | delivered_with_issues boolean on all 3 deliverable summary builders; announcement forced delivery records source_type=delivered_with_issues; parity tests; additive type in types.ts | 0abb831 | Tier A clean; Tier B backend 141; frontend build; Tier C sweep (167 pytest, 20 e2e) |
| I-008 | Vite-injected bundle version, badge mismatch warning, deployment_check --check-frontend-assets + unit test + badge e2e | 3ef215e | Tier A clean; risk-hardening 37; e2e 21 |
| I-009 / I-004 | Long-press active-project deletion e2e; language-table classifier 1000-row boundary unit test | 68b77de | Tier A clean; e2e 22; risk-hardening 41 |
| Backlog/cases | I-001..I-010 marked done with evidence; validation cases 007/008 extended for new markers/checks | 064d730 | n/a (docs) |

## Audit Findings

| Priority | Finding | Action |
|---|---|---|
| P2 | I-001/I-003/I-004/I-005/I-006/I-009/I-010 already fixed by earlier hardening; gaps were untested behaviour | Regression tests added (see above) |
| P1 | I-007 recovery existed everywhere but issue-carrying delivery metadata was inconsistent across translation/announcement | Fixed in 0abb831 |
| P1 | I-008 badge showed backend version even with a stale frontend bundle; deployment_check ignored frontend assets | Fixed in 3ef215e |
| P2 | errors.py UserFacingError hierarchy existed but was never wired to a handler (built, unused Seam) | Wired in 7e006c5 |
| Info | workflow/glossary/scripts/extract_glossary.py runs parallel to backend runtime | Scope documented as agent-side tooling; convergence deferred |

## Validation

| Tier | Command | Result |
|---|---|---|
| A | compileall + ruff E9,F (+ frontend build when touched) | pass every batch |
| B | risk_hardening + workflow_e2e + multilingual x2 (+e2e where required) | pass (137/141 backend, e2e 21/22) |
| C (mid-loop) | full pytest + build + e2e after batch 5 | 167 pytest, 20 e2e, all pass |
| C (final) | full pytest + build + e2e after final code change | 172 pytest, 22 e2e, all pass |
| D | deployment_check --expect-version 1.0.3 --check-frontend-assets on 127.0.0.1:5174 | all 4 steps ok (version, frontend_assets 2/2 match, health, upload readability) |
| D | stability_check on 127.0.0.1:5174 | 28/28 steps ok, test project deleted |
| E | not run | packaging/deployment files unchanged (deployment_check.py is a check script, not a package rule; build_release_package.py untouched) |

## Model Dispatch

| Role | Model | Scope | Result |
|---|---|---|---|
| Architect | Fable5 (main thread) | 2 architecture checkpoints (extract_glossary scope, candidates A-F approval), 3 risky-diff reviews (batches 1, 5, 6), Tier C/D orchestration, final acceptance | decisions in model-dispatch-log.md |
| Executor | Sonnet 5 (subagent, single resumed session) | Task 1 bulk read (68 files), Task 2 audit, batches 1-8 implementation and focused verification | all batches green, no Interface deviations |
| Validator | Fable5 (main, mechanical) | Tier C/D command runs and triage | pass |

## Manual Cases

| Case | Result | Evidence |
|---|---|---|
| 001 new translation to delivery | pass | e2e EN workflow + stability steps 09-13 |
| 002 direct QA | pass | e2e direct QA + stability 14-16 |
| 003 full language table candidates | pass | e2e block/accept + boundary unit test |
| 004 multilingual archive | pass | e2e wide glossary/archive + multilingual pytest |
| 005 quick task | pass | e2e quick task x2 + stability 20-22 |
| 006 announcement TXT delivery | pass | e2e announcement + stability 23-28 |
| 007 hard block recovery | pass | manual-fix-flow e2e + delivered_with_issues tests |
| 008 online/local smoke | pass | deployment_check + stability_check 28/28 on Tier D stack |

Details per case: docs/superpowers/reports/fable5-validation-log.md.

## Deferred

| Item | Reason | Next step |
|---|---|---|
| Candidate C provider readiness unification | Frontend/backend gates work and are tested; readiness-signal unification needs the cloud+test-fake policy decision first (rejected as a hard block this loop because CI depends on test-fake) | Future loop: backend-owned readiness field consumed by all launch surfaces |
| Candidate E / large text productization | Product delivery already enforces existence + non-empty checks; full gate parity (cache-lint/apply-dry-run/readback as a product Module) is feature-scale work owned by the 2026-07-07 plan | Execute 2026-07-07-large-text-workbench-productization.md as its own plan |
| Candidate F frontend workflow state Module | main.tsx is shallow-but-huge but pinned only by e2e; hook extraction is a cross-flow redesign with high regression cost and no user-facing gain this loop | Extract one domain hook when a feature batch already touches that domain |
| Candidate D language table classification | No material friction; boundary test added instead | none needed |

## Blockers

| Blocker | Evidence | Required help |
|---|---|---|
| none | Tier C/D fully green; two transient issues (port 8000 owned by a pre-existing unrelated backend, orphaned Vite child on 5174) were resolved by using a dedicated port 18000 stack and killing only the loop's own child process | n/a |
