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

## Optimization Closeout (2026-07-08 16:45–18:00)

架构检视报告（architecture-review-2026-07-08.md）优化项收口记录。执行方式：主线程（Fable5）调度，两个 Sonnet 5 后台子 agent 在隔离 worktree（独立 TEMP/端口）并行执行，串行推送。

### 收口项与证据

| 项 | 处置 | 验证 | Commit |
|---|---|---|---|
| E-剩余+N-7 大文本产品化收尾 | 本轮主线程完成（见 Large-Text Takeover 节） | 全量 186 + e2e 22/22 | fd9a0f3 及之前 |
| N-1 同名覆盖 bug（P1） | `_cell_text`/`_header_map` 改名 `_delivery_*` 恢复 strip 语义；新增 AST 守卫测试 test_workflow_namespace_guard.py（9 组重名逐一判定：1 真 bug、10 条白名单等价拷贝，白名单带源码一致性校验）+ 含空格 ID 合并回归测试 | 聚焦 116 passed；全量 189 passed（基线 186+3 新测试） | 98a64ee (merge) |
| N-2 交付摘要 shape 三处手写 | 新增 `_build_deliverable_summary` 单一构造入口，三处调用统一，输出逐字段不变 | 同上 | e755345 |
| N-3 单任务约束 | 按报告结论代码不动，约束写入 CLOUD_DEPLOYMENT.md | n/a | 05f4fbc |
| N-6 工具层双重角色 | CONTEXT.md 增加 Dual Role 节（runtime harness vs agent-only） | n/a | 32ded74 |
| N-8 双实现 parity 契约 | gate 侧文件头补 parity 契约说明（product 侧已有） | n/a | 32ded74 |
| 上游同步试跑（U3） | 判定 U3 小同步：glossary 文档/资产补齐（修复 README 坏链）、localization requirements 补 python-docx、补公告 docx 测试；副本领先部分不反向覆盖 | 四条 ITERATION.md 契约 CLI 冒烟全过；上游套件 154+44；parity 8；全量 186 | c6e78e4 (merge) |
| 上游流程文档修订 | 试跑暴露 5 处流程缺陷全部落档：基线套件分目录执行、diff 先 git archive 去噪、副本领先处置规则、同步 commit 固定格式、worktree 隔离推荐 | n/a | 8b33cb2 |

### 收口过程中的问题（先于成果记录）

1. 主线程一次 Await 中断连带断开两个子 agent 流，且遗留孤儿 pytest 进程锁住共享 lws-test-data SQLite，导致恢复后 parity 测试 2 个 setup 错误——清进程+隔离重跑通过。教训：并行子 agent 必须隔离 TEMP（本轮已做），中断恢复时先清理遗留进程。
2. 流程文档初版的验证命令（仓库根跑 workflow 套件）实际跑不通，靠残留 PYTHONPATH 掩盖；试跑清环境后才暴露。已修订文档。
3. 上游 localization 工作树有 30 个未提交 WIP 文件，diff 方向易失真；已把"只认已提交内容 + git archive 快照"写入流程。

### 明确不做/待触发项

- N-4（db.py glossary 规则上移）：下次改术语功能时顺手拆。
- N-5（run metadata 并发合并）：出现 metadata 丢失事故前不动。
- N-3 代码（任务锁粒度）：云端多用户成为真实需求时再演进。
- C（provider readiness 单一信号）：下次触碰任一 readiness seam 时顺手收。
- F（main.tsx 拆分）：extract-on-touch，不立项。

最终状态：master == origin/master @ 98a64ee，工作区干净，临时 worktree/分支/TEMP 目录全部清理。

## Model Budget Notes

- Default executor model: Sonnet 5 (claude-sonnet-5-thinking-high subagents)
- Fable5 used for: architecture checkpoints, risky diff review, final acceptance (main thread)
- Fable5 avoided for: bulk reads, grep scans, line counts, mechanical patches, report updates, command execution
