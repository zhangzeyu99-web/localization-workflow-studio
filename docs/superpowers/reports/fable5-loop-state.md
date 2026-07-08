# Fable5 Loop State

## Baseline

- Repo: D:\codex\localization-workflow-studio
- Branch: codex/fable5-full-audit-refactor (from master @ 1d30ff6)
- HEAD: 1d30ff6 chore: update 1.0.3 repo metadata
- Started: 2026-07-08 12:02 (UTC+8)
- Initial untracked files: docs/superpowers/plans/2026-07-07-large-text-workbench-productization.md, docs/superpowers/plans/2026-07-08-fable5-full-audit-refactor-loop.md
- Baseline note: matches plan expectation except the additional untracked plan file 2026-07-08-fable5-full-audit-refactor-loop.md (this plan itself); no other divergence.

## Current Phase

- Phase: Task 3 main work loop
- Phase status: COMPLETE
- Current item: final acceptance done
- Last validation tier: Tier C (172 pytest, 22 e2e) + Tier D (deployment_check 4/4, stability_check 28/28)
- Last validation result: pass
- Active model role: Architect (Fable5) final acceptance
- Last Fable5 checkpoint: 2026-07-08 15:50 final acceptance of compact final report

## Batch Log

| Batch | Scope | Files | Validation | Commit | Result |
|---|---|---|---|---|---|
| 1 | I-002 + Candidate A narrow: app-level UserFacingError handler + status mapping + cross-router no-leak tests | backend/app/errors.py, backend/app/main.py, backend/tests/test_risk_hardening.py | Tier A clean; risk-hardening 33 passed; Tier B backend 137 passed | 7e006c5 | pass |
| 2-4 | I-001/I-003/I-010 regression tests only (upload format 400, deliverable file-deleted, keyless preflight no-provider-call) | backend/tests/test_risk_hardening.py, backend/tests/test_workflow_e2e.py | Tier A clean; 3 focused passed; 134 passed full on touched files | b4aa443 | pass |
| 5 | I-007 + Candidate B narrow: delivered_with_issues field on all 3 summary builders; announcement forced delivery records source_type=delivered_with_issues | backend/app/workflow/delivery.py, backend/app/workflow/announcement.py, backend/tests/test_risk_hardening.py, backend/tests/test_workflow_e2e.py, frontend/src/types.ts | Tier A clean; Tier B backend 141 passed; frontend build OK | 0abb831 | pass |
| Tier C | full sweep after batch 5 | n/a | compileall/ruff clean; pytest 167 passed; build OK; e2e 20 passed | n/a | pass |
| 6 | I-008: Vite-injected bundle version, badge mismatch warning, deployment_check --check-frontend-assets + unit test + badge e2e | frontend/vite.config.ts, frontend/src/vite-env.d.ts, frontend/src/main.tsx, frontend/src/styles.css, scripts/deployment_check.py, backend/tests/test_risk_hardening.py, frontend/e2e/studio-ui-flow.spec.ts | Tier A clean; risk-hardening 37 passed; e2e 21 passed | 3ef215e | pass |
| 7-8 | I-009 deletion e2e (long-press modal, list refresh, surviving project landing) + I-004 classifier 1000-row boundary unit test | frontend/e2e/studio-ui-flow.spec.ts, backend/tests/test_risk_hardening.py | Tier A clean; e2e 22 passed; risk-hardening 41 passed | 68b77de | pass |
| docs | backlog statuses I-001..I-010 done + validation cases 007/008 extended | docs/optimization/* | n/a | 064d730 | pass |
| Tier C final | full sweep after final code change | n/a | compileall/ruff clean; pytest 172 passed; build OK; e2e 22 passed | n/a | pass |
| Tier D | deployment_check --check-frontend-assets + stability_check on isolated 5174/18000 stack | n/a | 4/4 + 28/28 steps ok, test project deleted | n/a | pass |

## Blockers

| Time | Command/Action | Failure | Attempts | Next Decision |
|---|---|---|---|---|
| 2026-07-08 15:26 | uvicorn on port 8000 for Tier D | Port owned by pre-existing unrelated backend (real data root, PID 10384) | 1 | Left untouched; used dedicated port 18000 stack |
| 2026-07-08 15:28 | vite on port 5174 | Orphaned node child from loop's own earlier launch held the port | 1 | Killed only the loop's own child process, relaunched cleanly |
| 2026-07-08 15:31 | stability_check first run | settings.json provider hand-written file normalized back to openai (settings live in settings.local.json) | 1 | PATCH /api/settings provider=test-fake, rerun passed 28/28 |

## Large-Text Takeover (2026-07-08 15:30+)

Fable5 主线程接手外部会话遗留的大文本产品化工作（plan: 2026-07-07-large-text-workbench-productization.md）。

| Step | Scope | Validation | Commit | Result |
|---|---|---|---|---|
| 复审 | 外部会话已提交 Task 1-5（39a5e05..fd9bf0a），未提交 Task 6/7 前端+文档改动；package-lock.json 幽灵改动已还原 | 后端聚焦 29 tests + harness parity 16 tests 全过（首轮 3 个失败为共享 LWS_DATA_ROOT 串扰，隔离重跑全过） | n/a | pass |
| 架构修正 | readback gate/retro 是过程产物，不得进交付 files（违反“交付只留最终文件+QA摘要”规则且破坏前端 2 文件契约）；改存 project qa_gates 目录，仅保留 artifact 记录和 metadata | test_multilingual_delivery 13 passed; test_workflow_e2e 99 passed; e2e 22/22 passed | 71ed8e5 | pass |
| Task 6 | Step 7 大文本面板 + RunDetail 门禁产物链接 + large_text_mode=auto 透传 + e2e 断言 | build OK; e2e 22/22 | 4b275b1 | pass |
| Task 7 | LARGE_TEXT_MULTILINGUAL_WORKFLOW/FEATURE_MATRIX/STABILITY_TEST_LIST 产品门禁文档 + 收编 07-07 plan 文件 | n/a | 293a8f7 | pass |
| Task 8 | 公告 AI 补充契约：provider_status=packet_fallback、report_only 计数、Step 4 UI 状态区分（API 复查/外部导入/检查包降级）+ 项目名缺译警告 + packet fallback 回归测试 | 公告聚焦 4 tests + glossary 39 tests + test_workflow_e2e 100 passed; 公告 e2e passed | 24ae795 | pass |
| 合并 | master 缓存修复 6464449 并入本分支 | 全量 pytest 186 passed; e2e 22/22 passed; build/lint/compileall clean | a78aea7 | pass |

嵌入式 glossary extractor 与独立仓 v0.3.0 对比：仅 Windows UTF-8 stdio 加固差异，按计划保留，不覆盖。

## Model Budget Notes

- Default executor model: Sonnet 5 (claude-sonnet-5-thinking-high subagents)
- Fable5 used for: architecture checkpoints, risky diff review, final acceptance (main thread)
- Fable5 avoided for: bulk reads, grep scans, line counts, mechanical patches, report updates, command execution
