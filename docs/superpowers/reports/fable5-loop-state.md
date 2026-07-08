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

## Frontend Optimization + Multiuser Concurrency Overnight Run (2026-07-08 20:33 – 07-09 04:45)

用户指令：今晚连续派发完成前端优化（含视觉）与多人化改造全部阶段，留恢复备份，明早完整验收。执行模式：Fable5 主线程调度 + 检查点，Sonnet 5 子 agent 隔离 worktree 执行，两条线并行、串行推送。计划文档：2026-07-08-frontend-optimization.md、2026-07-08-multiuser-concurrency.md。发布版本 v1.0.4 → **v1.1.0**（tag 已推送）。

### 阶段记录

| 阶段 | 内容 | 验证 | 合并点 |
|---|---|---|---|
| F1 提示语人话化 | uiText.ts 文案层 + 操作名错误兜底；修复 STEP 编号/英文状态/settings.local.json 直出等全部已确认问题；~8 处原生 alert/confirm 换 ConfirmModal；e2e 断言同批更新 | build/tsc 干净；e2e 22/22（主线程复验） | 0584e8a |
| M1 并发安全地基 | SQLite WAL+synchronous=NORMAL；merge_run_metadata/merge_announcement_task_metadata 原子合并替换 46 处（远超预估 15 处）；cancel_translation_run lease job_id 前缀修复；顺手修 conftest 等待竞态 | 全量 196 passed（189+7） | 8816bbd |
| F2 结构拆分 | main.tsx 2500→596 行（modals/ProjectOverview/4 组轮询 hooks/4 组域 action hooks）；TranslationWizard 2167→142 行（9 步独立文件+RunDetail 等） | 两次 e2e 22/22；纯搬家零行为变化 | 90a7667 |
| M2 锁粒度 | lease 改 long_text:{project_id}（同项目互斥、跨项目并行）；全局上限 max_concurrent_ai_jobs 默认 2 clamp 1-4；project_busy/capacity 结构化 409；GET /api/system/active-jobs；恢复路径按前缀清理；metadata={** 复发守卫测试；顺手修 project_dir 并发删除竞态 | 全量 203 passed ×2（196+7）；恢复中断一次（基础设施故障，断点续跑完成） | ddfc418 |
| F3 性能 | run 活跃时暂停快照轮询（10s 窗口请求 -25%）；热路径 memo/useCallback；三大向导 React.lazy（主包 445KB→371KB，-17%）；历史/动态列表 50 行分页；F2 发现的死代码清理 | 两次 e2e 22/22；pytest 196 无牵连 | 391934d |
| F4 视觉规范 | :root 约 60 个 token（色板/间距/圆角/字号）；卡片类收敛 .surface-card；补 640px 断点；9 组前后截图对比无跳变（D:\codex\lws-f4-screenshots\ 保留待验收） | e2e 22/22 ×2；只改 styles.css 一个文件 | d94775b |
| M3 资源共享 | SharedRateLimiter 进程级按 (provider,key) 分桶，跨线程/事件循环合计速率不超配额（反向验证：去锁 100% 丢数据）；settings 启动快照消灭中途 load（qa/semantic_qa/model_fixes/multilingual/glossary/project_analysis）；project 文件锁；删除项目防护 409 | 全量 213 passed ×2（203+10） | 1c65802 |
| M4 活跃任务面板 | header 徽章+面板（useActiveJobsPolling 9s）；排队 409 提示附"查看活跃任务"内联引导（公共 ActionStatus 一点覆盖）；新增 3 条 e2e | e2e 25/25（22+3）；pytest 213 | 77f9b50 |
| M5 部署收尾 | scripts/concurrency_smoke.py（11 步全过：并行翻译/active-jobs 同时可见/上限 409/无 database is locked）；CLOUD_DEPLOYMENT 并发模型改写；STABILITY_TEST_LIST +7 项；版本联动 6 文件 + docs/releases/v1.1.0.md；Tier D：deployment_check 4/4 + stability_check 29/29 + 冒烟全过（18800 隔离实例）；操作人昵称留痕（X-Operator 头 + 事件前缀 + 删除审计） | 全量 218 passed；v1.1.0 tag | 5c5c71a |

### 恢复锚点（均已推送远端）

backup/pre-fe-multiuser-20260708（a0bbae5 开工前）、backup/pre-f2（0584e8a）、backup/pre-f3（90a7667）、backup/pre-f4（391934d）、backup/pre-m2-merge（90a7667）、v1.1.0（5c5c71a）。整体回退：`git reset --hard backup/pre-fe-multiuser-20260708`；数据目录独立不受代码回退影响。

### 过程问题（先于成果）

1. 两个子 agent 各发生一次基础设施中断（F1 收尾时连接断开、M2 验证时流关闭），均为客户端故障非任务失败；断点恢复完成，F1 由主线程复验 e2e 兜底。教训已有：恢复时先清孤儿测试进程和 SQLite 锁残留。
2. WAL 提速暴露 conftest 等待竞态、并行化暴露 project_dir mkdir/rmtree 竞态——都是"提速/放开并发揭示既有时序假设"的实例，均已修复并留回归测试。
3. test-fake 任务过快导致 M4 e2e 无法稳定捕获运行态，改用路由拦截做确定性造数（后端锁语义由 pytest 覆盖，前端只验渲染逻辑），属合理分层。

### 外部会话衔接

隔壁会话于 22:11-22:12 直接向 master 提交了两个技术仓库的更新（12ef763 localization agent 工具层拆分、92ed2b4 glossary v0.4.0 同步宣告 SYNC.md、2cdc4fd v1.0.4 发布记录），带完整验证证据。上游 followup 主体已落地，明早验收确认即可。

### 明早验收清单

- [ ] 打开 http://127.0.0.1:5173/（已重启到 v1.1.0），头部版本徽章应显示 v1.1.0
- [ ] 过一遍主流程：提示语是否更明白、确认框是否为应用内弹窗
- [ ] 视觉对比 D:\codex\lws-f4-screenshots\before|after（应"更整齐"而非"变样"）
- [ ] 双开浏览器窗口模拟两人：不同项目同时跑翻译（test-fake 或真实 key）、观察活跃任务徽章、同项目第二任务的排队提示
- [ ] 设置里填操作人昵称后做一次交付，任务事件里应有 [昵称] 前缀
- [ ] docs/releases/v1.1.0.md 与 CHANGELOG 内容核对

## Model Budget Notes

- Default executor model: Sonnet 5 (claude-sonnet-5-thinking-high subagents)
- Fable5 used for: architecture checkpoints, risky diff review, final acceptance (main thread)
- Fable5 avoided for: bulk reads, grep scans, line counts, mechanical patches, report updates, command execution
