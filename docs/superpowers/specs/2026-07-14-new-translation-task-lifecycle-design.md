# 新翻译任务生命周期设计

## 目标

把“项目”和“翻译任务”拆成两个明确层级：项目长期保存资料、术语、译文归档和历史；每次“新翻译任务”创建一个独立任务，从 1/9 开始，不继承上一任务的来源、Run、QA、术语候选或交付状态。

本次同时解决三类问题：完成 T1 后能顺畅开始 T2；中断任务能按完整任务恢复；T1 的迟到异步结果、修复链和交付文件不能进入或覆盖 T2。

## 已确认问题

1. 项目总览和侧栏的“新翻译任务”目前只切换视图，没有建立任务边界。
2. 完成交付后再次进入会被旧的 `step`、Run、QA 和交付快照带回 9/9。
3. 仅按项目最新 Run 恢复会把多语言任务拆成单个 Run，丢失语言集合和真实阶段。
4. `passed` 不等于已交付，`failed` 也可能已经生成交付；仅靠 Run status 无法判断任务是否结束。
5. 同一项目内 T1 的异步请求可能在 T2 建立后返回，并继续写入 T2 的页面状态。
6. QA 手工修复和模型修复 Run 没有完整继承根来源，后续多语言合并可能选不到修复后的结果。
7. 多语言交付名只精确到分钟时，快速连续交付或重新生成会覆盖历史文件。
8. 现有 E2E 会直接跳到处理步骤并依赖自动选中项目最新来源，与“新任务来源为空”的契约冲突。

## 设计原则

- “新翻译任务”表示创建新任务；“继续当前任务”是独立、显式的分支。
- 项目资料可以复用，任务运行数据必须按 `translation_task_id` 隔离。
- 是否结束由持久任务终态决定，不从单个 Run status 猜测。
- 恢复单位是一个任务组，不是一个最新 Run。
- 新任务所有异步写回都必须同时匹配项目、任务和会话代次。
- 已完成、已放弃任务留在历史中；不删除 Run、Artifact、归档或交付文件。
- 新字段兼容历史数据；带任务 ID 的新请求不得回退到无 ID 的旧 Run。
- 英文新界面、新模板和新 XLSX/CSV 导出只保留一个 `EN` 主译列；历史 `EN2/target_alt` 继续允许导入和读取，但不再显示或继续生成。
- 不新增页面或视觉体系，复用现有步骤条、按钮、确认弹窗和状态提示。

## 数据契约与持久终态

### Run metadata

同一正式翻译任务产生的所有 translation/QA Run 都携带：

```text
translation_task_id: string
translation_task_state?: "delivered" | "abandoned" | "closed"  # closed 仅兼容历史数据
translation_task_state_updated_at?: ISO-8601 string
```

- `translation_task_state` 缺失表示任务仍为 `open`，避免为每个普通进度重复写状态。
- `delivered`、`abandoned` 是当前流程写入的持久终态标记；历史 `closed` 继续按终态读取。标记必须写到该任务已有的全部 Run；写入使用 metadata merge，不能覆盖质量、进度或来源字段。
- 当同一任务的 Run 上出现不同标记时，以 `translation_task_state_updated_at` 最大的标记为准；不能依赖 Run 列表顺序或第一个非空值。
- 无 Run 的纯前端草稿只存在当前浏览器会话；放弃时直接删除会话。本次不承诺跨刷新恢复这种草稿。

### 派生展示状态

| 展示状态 | 判定 |
| --- | --- |
| `draft` | 持久终态缺失，且没有 `queued/running` Run |
| `running` | 持久终态缺失，且任务组内任一正式 Run 为 `queued/running` |
| `needs_action` | 持久终态缺失，且存在 `needs_input/canceled/failed` 或已通过但尚未交付的结果 |
| `delivered` | 持久终态为 `delivered`；交付页仍可作为当前会话显示 |
| `abandoned` | 持久终态为 `abandoned`；只在历史中显示 |
| `closed` | 兼容历史数据；按已结束处理，只在历史中显示 |

关键边界：

- `passed` 但没有 `delivered` 标记仍是未完成任务，点击新任务时必须“继续 / 放弃”。
- 即使最新 Run 为 `failed`，只要持久终态为 `delivered` 或历史 `closed`，也不得再次弹出未完成任务。
- `delivered`、`abandoned` 和历史 `closed` 永远不参与“新翻译任务”的自动恢复；刷新后也不能复活。

### 状态迁移

```text
open -> delivered
open -> abandoned
```

- 单语或合并交付成功并且真实下载文件已产生后，由交付后端把对应任务标为 `delivered`。
- “放弃草稿并新建”在任务已有 Run 时，先调用任务放弃接口；运行中的任务禁止放弃。
- `delivered` 本身就是已完成终态；“返回项目”“开始下一翻译任务”以及已交付页顶部“项目概览”把当前会话标记为已交付或直接用新任务会话覆盖，不再增加一次后端关闭请求。
- `abandoned` 和历史 `closed` 为不可逆终态；对历史 closed 任务重新生成交付不得把它改回 `delivered`。
- 状态写入接口必须幂等，并校验任务属于当前项目。

## 任务分组与恢复

### 正式任务组

前端先把项目正式 Run 聚合为 `FormalTranslationTask`，再做入口和向导恢复：

```text
id / translationTaskId
runs[]
latestRun
sourceArtifactId
selectedLanguages[]
persistedState
derivedStatus
resumeStep
```

分组规则：

1. 有 `translation_task_id` 的 Run 只与相同 ID 的 Run 分组。
2. 组内 Run 按 `updated_at`、`created_at`、`id` 做稳定降序；不能假定 API 原始顺序。
3. 根来源按 `multilingual_source_artifact_id -> parent_input_artifact_id -> translation input_artifact_id` 解析。
4. 多语言选择由该任务 translation Run 的语言并集恢复；当前会话仍存在时，以会话保存的 `selectedLanguages` 为准。
5. QA Run、手工修复 Run、模型修复 Run 都属于原任务组，不得成为新的单 Run 任务。

恢复阶段：

- 有运行中的 QA Run，或任务已经进入 QA 链：8/9。
- 有运行中的 translation Run：7/9。
- translation 已结束、等待进入 QA：8/9。
- `needs_input` 原因为术语候选未确认或选定术语为空：5/9。
- `delivered` 任务只有从历史显式打开时进入 9/9；“新翻译任务”入口不会恢复它。
- 没有 Run 的会话使用会话保存的步骤。

### 历史兼容

- 无 `translation_task_id` 的旧 Run、Artifact 和交付继续可在历史中读取；旧 API 请求不带 ID 时保留现有来源/语言回退。
- 新请求一旦带 ID，查找、状态、QA 和交付都必须精确匹配，匹配不到就返回空或明确错误，不能借用 legacy Run。
- legacy `queued/running` Run 仍会阻止静默并发，并带用户回已有处理入口。
- legacy 非运行 Run 不作为新任务的隐式草稿自动复活；仍可从历史或任务面板走原有续跑入口。
- 本次不做批量历史迁移，也不要求给所有旧 Run 补任务 ID。

## 新任务入口决策

项目总览和侧栏入口共用同一个处理函数，按以下顺序：

1. 当前项目存在非终态 `running` 任务组，或同一任务的前端启动动作仍未结束：不创建新任务，恢复完整任务组；存在多个异常活跃组时打开后台任务面板，不猜测某个 Run。
2. 当前项目存在当前会话或最新的非终态正式任务组：弹出确认框。
   - 次操作：`继续当前任务`
   - 危险操作：`放弃草稿并新建`
3. 当前会话/任务组为 `delivered`、`abandoned`、`closed`，或没有未完成任务：直接创建新任务，从 1/9 开始。

开始新任务时必须生成全新的 `translation_task_id`，并清空任务级状态。即使 T2 选择与 T1 相同的来源和语言，也必须创建新的 Run。

## 前端会话与异步隔离

### 每项目会话

当前浏览器会话为每个项目保留：

```text
translationTaskId
generation
step
sourceArtifactId
selectedLanguages
glossaryBatchId
status
```

项目切换时只恢复该项目的任务会话或持久任务组。写会话前必须确认 hydration 已完成且项目 ID 未变化，避免把 A 项目状态写进 B 项目。

### 新任务清空范围

- 当前步骤、补充说明和来源选择
- 当前 translation/QA Run、QA 输入和问题列表
- 多语言选择、状态和进度板
- readiness、无效来源提示和逐句审校开关
- 当前交付快照、下载列表和合并结果
- 本次术语候选、预览和 `glossaryBatchId`

保留项目描述、参考资料、项目术语库、译文归档、历史 Run/Artifact/交付和其他项目页签状态。新任务默认语言为 EN，来源保持空白，不自动选择项目最新文件。

### stale guard

每个异步动作开始时捕获 `{projectId, translationTaskId, generation}`。每次 `await` 返回后、任何向导状态写入前，都必须通过 `isCurrentTranslationTask(token)`；新建、放弃、离开当前任务或切换项目时递增 `generation`。

- 迟到响应可以作为 T1 历史完成写入后端，但不能再更新 T2 的 `latestRun`、QA、quality issues、语言进度、readiness、交付文件或状态提示。
- Run polling 和项目快照可以刷新项目历史；向导只能从当前任务组派生数据。
- 术语候选只按当前会话保存的 `glossaryBatchId` 恢复；新任务没有 batch ID 时不得回退到“项目最新批次”。
- `createDeliveryPackage(runId)` 等历史动作从目标 Run 推导任务 ID，不得把当前向导的 T2 ID写到 T1 交付上。

## QA 修复源链

创建手工修复或模型修复 QA Run 时统一复制：

```text
translation_task_id
parent_input_artifact_id
multilingual_source_artifact_id
```

同时保留对应的 `manual_fix_source_run_id`、`model_fix_source_run_id` 或 `source_run_id`。新的 `input_artifact_id` 可以指向修复后文件，但根来源字段不能被修复文件替代。

任务内来源查找允许沿上述 source-run 链回溯补齐根来源；回溯中的每个 Run 都必须匹配同一 `translation_task_id`。合并交付优先采用该任务内最新、可交付的修复后 QA Run。

## 交付隔离与命名

- 单语交付的任务身份取目标 Run；多语言交付必须显式接收 `translation_task_id`，并只合并该任务组内的语言结果。
- 交付成功后返回的 deliverable、Artifact metadata 和前端 `GeneratedDeliveryState` 都保存任务 ID。
- 合并交付每次生成独立 nonce，例如 `db.new_id("delivery")` 的短后缀；文件名采用：

```text
{project}_ALL_{YYYYMMDDHHMMSS}_{task_suffix}_{delivery_nonce}_final.xlsx
{project}_ALL_{YYYYMMDDHHMMSS}_{task_suffix}_{delivery_nonce}_qa_summary.xlsx
```

- `task_suffix` 便于人读，`delivery_nonce` 才是防覆盖保证。T1/T2 在同一分钟交付、同一任务重复生成，路径都必须不同；旧文件内容与 Artifact 指向保持不变。

## 交付后的操作

- 交付文件真实可下载后，底部显示次操作 `返回项目` 和主操作 `开始下一翻译任务`。
- `返回项目`：任务保留持久 `delivered` 终态，把当前会话标记为已交付，并把该项目向导导航位置重置为 1/9，再回项目总览。
- `开始下一翻译任务`：完成相同标记后立即创建新的任务 ID，用干净的新会话覆盖旧会话并进入 1/9。
- 从已交付页顶部“项目概览”离开时，交付生成后的状态同步已把会话标记为已交付；之后再点“新翻译任务”直接新建，不弹未完成提示。

## UI 与文案

- 草稿确认标题：`已有未完成翻译任务`
- 草稿确认正文：`当前项目还有未完成的翻译任务。你可以继续当前进度，或放弃这份草稿并创建全新任务。`
- 运行中提示：`当前项目已有任务正在运行，已带你回到当前任务。`
- 新任务提示：`已创建新的翻译任务。`
- 交付后主按钮：`开始下一翻译任务`
- 交付后次按钮：`返回项目`

确认弹窗继续使用现有焦点管理、Esc 关闭和按钮样式。

## 验收标准

1. T1 交付后，`translation_task_state=delivered` 持久存在；返回项目或开始下一任务后仍为 `delivered`，且不会恢复成当前任务。
2. 放弃有 Run 的草稿后为 `abandoned`，刷新页面不会再次出现该草稿。
3. `passed` 但未交付的任务仍提示继续/放弃；`failed` 但已交付的任务直接允许新建。
4. 多语言任务按一个 task group 恢复全部语言和正确阶段，不退化成一个最新 Run。
5. T2 从 1/9 开始、来源为空、默认 EN；不显示 T1 的 Run、QA、术语候选、下载或合并结果。
6. 两个“新翻译任务”入口使用同一决策；运行中任务不新增 Run，未完成任务两个分支都正确。
7. T2 即使选择 T1 相同来源和语言，也创建新的任务 ID 和 Run；带 ID 查找绝不回退 legacy。
8. T1 的迟到请求和轮询结果不会写入 T2；项目历史仍能看到 T1 的真实结果。
9. 手工修复和模型修复后的 QA Run 保持任务 ID 与根来源，合并交付选到修复后结果。
10. T1/T2 同一分钟交付以及同一任务重复生成的文件名均唯一，旧文件未被覆盖。
11. 历史页面仍能读取无任务 ID 的旧 Run 和交付；legacy 运行任务仍阻止静默并发。
12. 项目切换恢复各自任务组的步骤、来源和多语言选择，不串项目。
13. 已交付页的 `返回项目`、`开始下一翻译任务` 和顶部 `项目概览` 都正确标记或覆盖当前会话，且不会让已交付任务重新成为当前任务。
14. E2E 新任务路径先在 4/9 显式选择来源，不依赖自动选中项目最新文件。
15. 聚焦后端测试、真实标题命中的生命周期 E2E、完整 E2E、前端构建和后端全量测试通过。
16. 真实浏览器复验无控制台错误、旧状态闪回或横向溢出回归。
17. EN 语言选择保持稳定；术语候选、新模板和新 XLSX/CSV 导出均无 EN2，同时旧 EN2 文件仍可兼容导入。

## 非目标

- 不新增持久化 `translation_tasks` 表或跨设备纯前端草稿同步。
- 不放宽项目级并发租约或重做后台调度。
- 不批量迁移、删除或重命名历史 Run、Artifact、交付和归档。
- 不修改 `workflow/localization` 或 `workflow/glossary` 只读同步产物。
- 不重做项目总览、步骤条或交付页视觉主题。
