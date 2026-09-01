# 新翻译任务生命周期实施计划

> 执行要求：所有行为改动按 red-green-refactor 推进；任务身份、持久终态、前端恢复和交付互相依赖，按 Task 1 至 Task 5 顺序实施。不得提交或推送。

**目标：** “新翻译任务”创建从 1/9 开始的隔离任务；未完成任务显式继续或放弃；运行中任务不静默并发；交付后能返回项目或直接开始下一任务；刷新、迟到请求、QA 修复和重复交付均不会串入或覆盖别的任务。

**架构：** 前端为每个正式任务生成 `translation_task_id`；后端把任务 ID 和 `delivered/abandoned` 终态保存在 Run metadata，并继续识别历史 `closed`。前端按任务 ID 聚合完整任务组，用任务组恢复来源、语言集合和阶段。所有异步写回同时校验项目、任务和会话代次。带任务 ID 的后端查找严格匹配；无 ID 请求保留 legacy 读取路径。

**技术栈：** React 19、TypeScript 5.7、Playwright、FastAPI/Pydantic、SQLite Run metadata、pytest。

## 全局约束

- 不修改 `workflow/localization` 或 `workflow/glossary` 只读同步产物。
- 保留现有未提交改动，包括 EN/EN2 修复、`scripts/start-workbench.ps1` 和 handoff 文档。
- 不提交、不推送。
- 不新增 `translation_tasks` 数据表；纯前端无 Run 草稿不做跨刷新恢复。
- 新任务清空任务状态，但保留项目资料、术语库、参考文件、译文归档和历史交付。
- `translation_task_id` 对旧 API 可选；一旦非空，任何 selector/lookup 不得回退 legacy Run。
- 项目总览和侧栏两个入口必须调用同一个 `openNewTranslationTask`。
- 每个生产改动前先增加能证明缺失行为的失败测试；修复后运行聚焦测试，再进入下一任务。

## 持久契约

Run metadata：

```text
translation_task_id: string
translation_task_state?: "delivered" | "abandoned" | "closed"  # 缺失即 open；closed 仅兼容历史数据
translation_task_state_updated_at?: ISO-8601 string
```

当前流程允许迁移：`open -> delivered`、`open -> abandoned`。`delivered/abandoned` 直接作为终态；历史 `closed` 继续按不可逆终态读取，重新生成交付不得重新打开。

前端任务组：

```text
FormalTranslationTask {
  id
  translationTaskId
  legacy
  runs[]
  latestRun
  sourceArtifactId
  selectedLanguages[]
  persistedState
  derivedStatus
  resumeStep
}
```

## 文件范围

后端：

- `backend/app/schemas.py`
- `backend/app/routers/runs.py`
- `backend/app/routers/delivery.py`
- `backend/app/workflow/translation_tasks.py`
- `backend/app/workflow/multilingual.py`
- `backend/app/workflow/delivery.py`
- `backend/app/workflow/qa.py`
- `backend/app/workflow/qa_model_fixes.py`
- `backend/tests/test_translation_task_lifecycle.py`
- `backend/tests/test_multilingual_orchestration.py`
- `backend/tests/test_multilingual_delivery.py`
- `backend/tests/test_workflow_e2e.py`（仅补 QA 修复链回归）

前端：

- `frontend/src/domain/translationTaskLifecycle.ts`
- `frontend/src/domain/translationFlow.ts`
- `frontend/src/main.tsx`
- `frontend/src/hooks/useTranslationActions.ts`
- `frontend/src/hooks/useRunStatusPolling.ts`
- `frontend/src/components/translationWizard/TranslationWizard.tsx`
- `frontend/src/components/translationWizard/MultilingualWorkflowBoard.tsx`
- `frontend/src/components/translationWizard/steps/StepTranslate.tsx`
- `frontend/src/components/translationWizard/steps/StepQA.tsx`
- `frontend/src/components/translationWizard/steps/StepDone.tsx`
- `frontend/src/types.ts`
- `frontend/e2e/studio-ui-flow.spec.ts`

---

## Task 1：建立任务身份和持久终态

### 1.1 先写后端失败测试

在 `backend/tests/test_translation_task_lifecycle.py` 增加并固定这些测试名：

- `test_delivery_marks_only_requested_translation_task_delivered`
  - 同项目创建 task-a/task-b；生成 task-a 交付后，仅 task-a 全部 Run 有 `delivered` 和同一 `translation_task_state_updated_at`。
- `test_abandoned_translation_task_stays_terminal_after_reload`
  - 放弃非运行 task-a 后重新读取项目；task-a 为 `abandoned`，查找未完成任务时不再出现。
- `test_marking_translation_task_delivered_twice_is_idempotent`
  - 交付终态重复写入保持幂等，不产生新的状态变化。
- `test_passed_without_delivery_remains_open`
  - Run status 为 `passed` 但没有任务终态时仍为 open。
- `test_failed_run_with_delivered_task_state_is_terminal`
  - 最新 Run 为 failed 但任务终态 delivered 时不得判成未完成。
- `test_delivered_does_not_reopen_terminal_translation_task`
  - abandoned 或历史 closed 任务重新生成文件后仍保持原终态。

在 `backend/tests/test_multilingual_orchestration.py` 增加：

- `test_run_create_persists_translation_task_id`
- `test_multilingual_status_with_task_id_never_falls_back_to_legacy_run`

### 1.2 验证 RED

```powershell
python -m pytest backend/tests/test_translation_task_lifecycle.py backend/tests/test_multilingual_orchestration.py -q
```

预期：新增测试因缺少终态守卫、最新标记解析或严格 no-fallback 失败；不得出现收集 0 项。

### 1.3 补请求字段和 metadata

在 `backend/app/schemas.py`：

- `RunCreate.translation_task_id: str | None = None`
- `MultilingualQueueRequest.translation_task_id: str | None = None`
- 合并交付请求增加同名可选字段。

在 `backend/app/routers/runs.py` 创建 Run 时，把非空 ID 写入 metadata；legacy 请求不强制生成 ID。

### 1.4 实现终态帮助函数

在 `backend/app/workflow/translation_tasks.py` 提供并只通过这些函数读写终态：

- `translation_task_runs(project_id, translation_task_id)`：只返回同项目、同 ID 的正式 translation/QA Run。
- `translation_task_state(runs)`：读取 `translation_task_state_updated_at` 最大的有效标记；相同时间用稳定 Run ID 决胜。
- `mark_translation_task_state(project_id, translation_task_id, state)`：校验迁移、用同一时间戳 merge 到全部 Run、保留其他 metadata，并返回更新 Run ID。
- `translation_task_continuation_metadata(source_run)`：Task 2 的 QA 修复共用。

具体守卫：

- `abandoned` 拒绝任务组内仍有 `queued/running`。
- 当前产品动作只写 `delivered/abandoned`；内部帮助函数继续识别历史 `closed`。
- `delivered` 不覆盖已有历史 `closed` 或 `abandoned`。
- 同状态重复调用幂等。
- 空 ID、跨项目或找不到任务返回明确 4xx，不允许按来源猜任务。

### 1.5 暴露状态动作并接入交付

在 `backend/app/routers/runs.py` 增加：

```text
POST /api/projects/{project_id}/translation-tasks/{translation_task_id}/abandon
```

在 `backend/app/workflow/delivery.py`：

- 单语交付从目标 Run metadata 取任务 ID。
- 合并交付从请求体取任务 ID。
- 只有真实下载文件和 Artifact 成功建立后才标 `delivered`。
- 已 abandoned 或历史 closed 的任务重新生成交付只新增历史产物，不改变终态。

### 1.6 验证 GREEN

```powershell
python -m pytest backend/tests/test_translation_task_lifecycle.py backend/tests/test_multilingual_orchestration.py -q
```

预期：0 failures。

---

## Task 2：隔离多语言、QA 修复源链和交付文件

### 2.1 先写多语言和修复链失败测试

在 `backend/tests/test_multilingual_orchestration.py`：

- `test_new_translation_task_does_not_reuse_same_source_child_run`
  - task-old/task-new 使用同一来源和语言；task-new 必须创建新 Run，status 只返回 task-new。
- `test_multilingual_qa_runs_keep_translation_task_id`
  - 多语言 QA 的每个子 Run 都继承任务 ID、根来源和对应语言。

在 `backend/tests/test_workflow_e2e.py`：

- `test_manual_fix_qa_run_preserves_translation_task_root_source`
- `test_model_fix_qa_run_preserves_translation_task_root_source`

两项都断言新 QA Run metadata 同时具有：

```text
translation_task_id
parent_input_artifact_id
multilingual_source_artifact_id
manual_fix_source_run_id 或 model_fix_source_run_id
```

在 `backend/tests/test_multilingual_delivery.py`：

- `test_merged_delivery_uses_only_requested_translation_task`
- `test_merged_delivery_prefers_repaired_qa_run_in_same_task`
- `test_merged_delivery_names_are_unique_within_same_minute`
  - 冻结时间，连续生成 task-a、task-b，再为 task-b 重生成一次；三个 final 路径和 summary 路径均不同，第一次文件哈希不变。
- `test_merged_delivery_with_task_id_never_uses_legacy_run`

### 2.2 验证 RED

```powershell
python -m pytest backend/tests/test_multilingual_orchestration.py backend/tests/test_multilingual_delivery.py backend/tests/test_workflow_e2e.py -q -k "translation_task or merged_delivery or fix_qa_run"
```

预期：旧 Run 复用、修复链根来源缺失、严格匹配或唯一命名至少一项失败。

### 2.3 统一多语言精确查找

在 `backend/app/workflow/multilingual.py`：

- `_matches_translation_task(run, translation_task_id)`：ID 非空时只接受完全相等。
- `_find_child_run`、translation/QA status、queue start、worker、QA input 和 passed/deliverable 查找全部接收任务 ID。
- 创建的 translation/QA Run metadata 写入任务 ID、`parent_input_artifact_id`、`multilingual_source_artifact_id`。
- job key 加入任务 ID，避免同来源不同任务共享后台 job。
- status response 回传任务 ID；找不到当前任务结果时返回 pending/空，不回退 legacy。

### 2.4 修复 QA continuation metadata

在 `backend/app/workflow/qa.py` 和 `qa_model_fixes.py`，创建新 QA Run 时调用 `translation_task_continuation_metadata(source_run)`，再加入修复特有 source-run 字段。

在合并来源查找中：

- 先筛同一任务 ID。
- 直接根来源缺失时，只可沿 `source_run_id`、`manual_fix_source_run_id`、`model_fix_source_run_id` 回溯同任务 Run。
- 候选按 `updated_at/created_at/id` 稳定降序，优先最新且有最终 Artifact 的修复后 QA Run。

### 2.5 保证合并交付名唯一

在 `backend/app/workflow/delivery.py` 每次调用 `build_merged_delivery_package` 都生成独立：

```python
delivery_nonce = db.new_id("delivery").removeprefix("delivery_")[:8]
```

final 和 QA summary 共用一个 stem：

```text
{project}_ALL_{YYYYMMDDHHMMSS}_{task_suffix}_{delivery_nonce}
```

不能只用分钟时间或 task suffix；重复生成不得覆盖既有路径。Artifact 和 deliverable metadata 保存任务 ID、nonce 和本次路径。

### 2.6 验证 GREEN

```powershell
python -m pytest backend/tests/test_multilingual_orchestration.py backend/tests/test_multilingual_delivery.py backend/tests/test_workflow_e2e.py -q -k "translation_task or merged_delivery or fix_qa_run"
```

预期：0 failures。

---

## Task 3：前端按完整任务组恢复和筛选

### 3.1 先写浏览器模块失败测试

在 `frontend/e2e/studio-ui-flow.spec.ts` 保留或增加以下真实标题：

- `formal workflow selectors isolate runs by translation task id`
- `wizard delivery run stays inside the current translation task`
- `translation task lifecycle groups multilingual runs and ignores closed tasks`
- `translation task lifecycle uses the newest persisted state marker`
- `passed translation without delivery remains an unfinished task`

断言覆盖：

- task-running 的 EN+KO translation/QA Runs 聚合成一个组，语言为两种，恢复到 QA 8/9。
- task-closed/task-abandoned 不被 active/unfinished selector 返回。
- 同组 Run 标记顺序打乱后，仍按 `translation_task_state_updated_at` 取最新终态。
- `passed` 且无终态仍是 unfinished。
- 当前 task-new 看不到 task-old/legacy 的 Run、QA 和 deliverable。

### 3.2 验证 RED 且确认标题真实命中

```powershell
npm --prefix frontend run e2e -- --list --grep "formal workflow selectors isolate|wizard delivery run stays|translation task lifecycle groups|translation task lifecycle uses|passed translation without delivery"
npm --prefix frontend run e2e -- --grep "formal workflow selectors isolate|wizard delivery run stays|translation task lifecycle groups|translation task lifecycle uses|passed translation without delivery"
```

预期：`--list` 至少列出 5 项；运行因分组、终态顺序或 unfinished 规则缺失失败，不得出现 `No tests found`。

### 3.3 实现任务组 domain

在 `frontend/src/domain/translationTaskLifecycle.ts`：

- `formalTranslationTasks(project)` 按非空任务 ID 分组；legacy Run 仅作为兼容单元，不与新 ID 混合。
- 组内 Run 稳定排序，计算最新 Run、根来源、translation Run 语言并集和最新持久终态。
- `findActiveFormalTask` 返回非终态且含 queued/running 的完整组。
- `findUnfinishedFormalTask` 返回非终态、非运行的 open 组；passed 未交付必须命中。
- legacy queued/running 可作为 active 阻止并发；legacy 非运行历史不自动成为新任务草稿。
- `translationTaskResumeStep(task)` 按完整组判 5/7/8；不能只看一个 latest Run。

### 3.4 让所有 selector task-aware

在 `frontend/src/domain/translationFlow.ts` 及向导步骤中，把 `translationTaskId` 传到：

- translation/resumable/visible Run selector
- QA/quality issue selector
- multilingual workflow items
- delivery Run 和 delivery files selector

规则：ID 非空时先做 exact-match；沿 QA source-run 链时每一跳仍须属于同任务。`wizardLatestRun` 从当前任务组得出，项目历史仍使用项目级列表。

### 3.5 扩展前端类型

在 `frontend/src/types.ts`：

- `GeneratedDeliveryState.translationTaskId?: string`
- `DeliverableTask.translation_task_id?: string`
- 多语言 status/response 增加可选任务 ID。

`StepTranslate`、`StepQA`、`StepDone`、`MultilingualWorkflowBoard` 和 `TranslationWizard` props 统一接收当前任务 ID/任务组，不在组件内部找项目最新 Run。

### 3.6 验证 GREEN

重复 3.2 两条命令，预期全部通过。

---

## Task 4：实现入口、会话、stale guard 和交付后动作

### 4.1 先补真实生命周期 E2E

在 `frontend/e2e/studio-ui-flow.spec.ts` 使用这些精确标题：

1. `new translation task lets the user continue or discard an unfinished draft`
2. `new translation task redirects to the active multilingual task without creating another run`
3. `translation task lifecycle groups multilingual runs and ignores closed tasks`
4. `multilingual task stays in one flow through translation, QA overview, and merged delivery`
5. `completed translation returns to a clean new task after project overview`
6. `user can complete the EN localization workflow from project tabs`
7. `stale source inspection cannot overwrite a replacement translation task`

新增测试必须分别证明：

- 项目总览入口和侧栏入口都走相同决策。
- 继续恢复原 task group 的来源、完整语言集合和步骤；放弃持久化 `abandoned` 后刷新也不复活。
- running task 不增加 Run 数量。
- 交付后 `返回项目 -> 新翻译任务` 和 `开始下一翻译任务` 都进入 1/9，来源为空、EN 选中、T1 下载/QA/语言卡为 0。
- 顶部“项目概览”离开 delivered 页时，会话已由交付状态同步标记为 delivered；持久终态保持 delivered。
- 延迟 T1 的 status/readiness/QA 响应到 T2 建立后再返回；T2 页面仍保持空白，T1 只出现在历史。

### 4.2 修正 E2E 的显式选源契约

新任务不自动选择项目最新文件。凡测试从“新翻译任务”进入 7/9 或依赖来源表头，先保存上传返回的 Artifact ID，再执行：

```typescript
await selectWizardStep(page, 4)
await page.locator('.step-panel.active label.asset-select select').selectOption(source.id)
```

然后才进入 6/9、7/9 或 8/9。至少修正这些现有标题：

- `project switches keep each workflow location and scope new translation after handling activity`
- `language table headers auto-select targets and start one multilingual queue`
- `multilingual task stays in one flow through translation, QA overview, and merged delivery`
- `translation evidence shows archive references and line proofreading stages`
- `workflow remains usable without page overflow at compact desktop and mobile widths`

`new translation task exposes the full supported language set` 只验证 6/9 语言控件，可不伪造来源，但不得让该测试证明处理步骤可绕过来源门禁。

### 4.3 验证生命周期 E2E 为 RED 且不是零匹配

```powershell
npm --prefix frontend run e2e -- --list --grep "new translation task lets|new translation task redirects|translation task lifecycle groups|multilingual task stays|completed translation returns|delivery next-task action|stale task completion"
npm --prefix frontend run e2e -- --grep "new translation task lets|new translation task redirects|translation task lifecycle groups|multilingual task stays|completed translation returns|delivery next-task action|stale task completion"
```

预期：`--list` 精确列出 7 项；至少新增的完成后、next-task 或 stale 测试因缺失行为失败。

### 4.4 建立每项目会话与干净 reset

在 `frontend/src/main.tsx` 保存：

```text
translationTaskId
generation
step
sourceArtifactId
selectedLanguages
glossaryBatchId
status
```

`beginFreshTranslationTask(projectId)`：

- 生成新 ID 并递增 generation。
- 清空来源、latest Run、QA Artifact/issues、多语言进度、readiness、无效来源、逐句审校、本次术语候选/batch、generated delivery 和下载列表。
- `selectedLanguages=['en']`，step=1，来源为空。
- 保留项目资料、项目术语、参考资料、归档和历史。
- 写会话前确认 `hydratedProjectId === projectId`，避免项目切换写串。

### 4.5 用任务组实现统一入口

`openNewTranslationTask` 的固定顺序：

1. `findActiveFormalTask(current)` 或当前 task start 仍 busy：`openFormalTaskInWizard(task)`，不创建新 Run。
2. 当前会话/`findUnfinishedFormalTask(current)`：弹现有确认框。
3. 继续：恢复 task group 的 ID、根来源、全部语言和 resume step。
4. 放弃：有 Run 时 await abandon API 成功，再清会话并 begin fresh；纯前端草稿直接替换。
5. delivered/abandoned/历史 closed 或无任务：begin fresh。

`openFormalTaskInWizard` 接收 `FormalTranslationTask`，不得接收单个 Run；QA/translation 阶段、来源和语言从组计算。

### 4.6 加同项目异步 stale guard

在 `main.tsx` 和 `useTranslationActions.ts` 统一使用：

```text
TaskActionToken { projectId, translationTaskId, generation }
captureTranslationTaskToken()
isCurrentTranslationTask(token)
```

每个 async action 在开始捕获 token；每次 await 后、每个向导 setter 前检查。新建、放弃、离开当前任务或项目切换时 generation 变化，使旧 token 失效。

必须覆盖：

- 单语创建/启动/续跑
- 多语言 translate/status/QA
- QA 手工修复/模型修复和 polling
- readiness 和来源验证
- quality issues 与 QA Artifact 回填
- merged/single delivery state
- 项目 snapshot hydration

后端已完成的旧任务结果仍可刷新到项目历史，但不能写 `latestRun`、当前状态提示或 T2 向导。

### 4.7 清除任务不相关的项目级回填

在 `main.tsx`、`useRunStatusPolling.ts` 和向导步骤：

- quality issues 只来自当前 task group 的 QA Run。
- run polling 可以更新项目快照；当前向导只消费 exact task ID 的结果。
- step >= 8 的 Run/Artifact 自动注入、generated delivery 和多语言卡全部 task-scoped。
- 术语候选只按会话 `glossaryBatchId` 加载；新任务 ID 建立后不得按“项目 + 语言最新批次”回填旧候选。
- 历史 `createDeliveryPackage(runId)` 从目标 Run 推导任务 ID；不能使用当前 T2 会话 ID，也不能把 T1 交付显示为 T2 当前交付。

### 4.8 接入交付后会话清理和 CTA

交付文件可下载后：

- `返回项目`：保留任务的 delivered 终态，把当前会话标记为 delivered；导航保存为 wizard step 1；回项目总览。
- `开始下一翻译任务`：执行相同标记后立即 `beginFreshTranslationTask`，由新会话覆盖旧会话。
- delivered 页顶部“项目概览”依赖交付状态同步完成同一会话标记。
- delivered 是充分的持久终态，不额外引入一次 close API 网络依赖。

在 `TranslationWizard.tsx` 的 9/9 底部同时显示两个按钮；交付文件未就绪时都禁用。

### 4.9 验证 GREEN

重复 4.3 两条命令，预期 7 项全部通过。

---

## Task 5：全量验证与真实浏览器读回

### 5.1 聚焦后端

```powershell
python -m pytest backend/tests/test_translation_task_lifecycle.py backend/tests/test_multilingual_orchestration.py backend/tests/test_multilingual_delivery.py -q
python -m pytest backend/tests/test_workflow_e2e.py -q -k "fix_qa_run"
```

预期：0 failures，且没有 0 项收集。

### 5.2 前端构建与标题门禁

```powershell
npm --prefix frontend run build
npm --prefix frontend run e2e -- --list --grep "new translation task lets|new translation task redirects|translation task lifecycle groups|multilingual task stays|completed translation returns|delivery next-task action|stale task completion"
```

预期：build exit 0；`--list` 列出 7 项，不出现 `No tests found`。

### 5.3 完整回归

```powershell
npm --prefix frontend run e2e
python -m pytest backend/tests -q
```

预期：0 failures。

### 5.4 真实浏览器验收

使用一次性项目，按相同视口验证：

1. step 4 草稿 -> 项目概览 -> 新任务 -> 继续：恢复同一 task group、来源和多语言选择。
2. 同一草稿 -> 放弃并新建 -> 刷新：仍在新任务，旧任务不复活。
3. queued/running 多语言任务 -> 新任务：回到完整语言板，不新增 Run。
4. T1 交付 -> 返回项目 -> 新任务：1/9、来源空、EN、无 T1 下载。
5. T1 交付 -> 开始下一翻译任务：同样干净进入 T2。
6. T1 交付 -> 顶部项目概览 -> 新任务：T1 保持 delivered，不弹未完成。
7. 同一来源连续完成 T1/T2 并重生成一次 T2：三个文件名不同，T1 下载内容未变化。
8. QA 手工/模型修复后交付：合并文件采用修复后内容。

检查 console 无错误，并观察切换语言、步骤和任务时没有旧状态“闪一下再消失”。

### 5.5 运行态与仓库边界

仅在前端未热更新时使用现有受保护启动脚本；重启前后检查 `/api/health`、5173 和独立监视进程，不终止监视器。

```powershell
git status --short
git diff --check
git diff --stat
git diff --name-only -- workflow/localization workflow/glossary
```

预期：无空白错误；只读同步目录无改动；用户原有改动保留；没有 commit/push。

## 自检清单

- [ ] `delivered/abandoned` 已持久化，历史 `closed` 可兼容读取；终态按更新时间解析，不靠 Run status 或列表顺序猜测。
- [ ] 恢复单位是 task group；多语言来源、语言集合和阶段都完整。
- [ ] passed 未交付、failed 已交付、刷新后 abandoned 以及历史 closed 三个边界都有测试。
- [ ] 同项目旧 async response、polling、quality issues、术语候选和 delivery 均有 task/generation guard。
- [ ] QA 手工与模型修复都保留任务 ID、根来源和 source-run 链。
- [ ] 合并交付每次生成 nonce，T1/T2 和同任务重生成均不覆盖。
- [ ] 生命周期 grep 使用上述真实测试标题，`--list` 精确命中 7 项。
- [ ] 新任务 E2E 在进入处理前显式选择来源，不依赖项目最新 Artifact 自动回填。
- [ ] 带 ID 查找不回退 legacy；无 ID 历史仍可读，legacy running 仍阻止并发。
- [ ] 两个入口、已交付后的返回/下一任务路径和项目切换均有验收。
- [ ] 未修改只读同步产物，未提交，未推送。

## 最终验证结果（2026-07-14）

- 前端生产构建通过。
- Playwright 全量回归：68 passed；覆盖语言选择延迟后不闪退、EN 单列、草稿继续/放弃、运行任务重定向、任务隔离、旧术语请求迟到保护、交付后返回项目并新建以及窄屏布局。
- 后端全量回归：261 passed；覆盖单语/合并交付删除 legacy EN2 且不误删非英语通用备用列，仅保留一条 Starlette/httpx 依赖弃用警告。
- 运行态读回：8000、5173、5174 均返回 200；后端通过受保护启动脚本重新加载，独立监视进程 PID 保持不变。
- 真实浏览器烟测：页面 200、工作台正常渲染、控制台零错误；EN 的 `alt_header` 为空且 EN2 仅保留为旧文件导入别名。
- 仓库边界：`workflow/localization` 与 `workflow/glossary` 无改动；未提交、未推送。
