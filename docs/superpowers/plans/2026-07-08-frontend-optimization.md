# 前端优化计划（2026-07-08）

> 目标：提示语让人明白（最高优先）、使用体验顺畅、页面速度、界面观感、代码结构拆分。
> 边界：不改业务语义、不改 API 契约、不引入状态库/UI 库/路由库，技术栈保持 React 19 + Vite + 原生 CSS。
> 执行模式：fable5 循环（主线程架构决策 + Sonnet 5 子 agent 执行），隔离 worktree，每阶段验证合并。

---

## 0. 事实基线（2026-07-08 探查，两组独立探查互相印证）

- `frontend/src/main.tsx` ~2500 行：单体 `App` 持有 30+ `useState`、60+ 内联 handler、13+ `useEffect`；`ProjectOverview`（~390 行、55+ props）、4 个 Modal 内嵌其中。
- `frontend/src/components/translationWizard/TranslationWizard.tsx` ~2100 行：9 个 Step 组件全部内联，另混入 `TaskHistoryTable`、`RunDetail`、QA 文案函数。
- 轮询 5 套 `setInterval`：项目列表 10s（main.tsx:97）、项目快照 6s（main.tsx:183）、run 详情 2s（main.tsx:309）、公告任务 2.5s（main.tsx:376）、快速任务 1.5s（QuickTaskWizard.tsx:120）。run 活跃时 6s 快照与 2s run 轮询并行重叠，无 in-flight 去重、无 AbortController；2s run 轮询无 `document.hidden` 检查。
- 全仓库 `React.memo`/`useCallback` 使用为 0；任何 state 更新全树重渲染，轮询期间每 2s 重渲一次。
- 无代码分割（无 `React.lazy`/动态 import）；无虚拟化；宽表已有 100 行分页（`assetTableState.ts`）。
- 文案：无统一静态文案层；`appText.ts`（~170 行）只做后端事件/状态的动态转换。已确认的问题文案（节选）：
  - main.tsx:345/350 暴露内部编号"请进入 STEP 8"；
  - TranslationWizard.tsx:1827/1876/1881 历史表和 RunDetail 直出英文 `run.status` 和裸 UUID；
  - domain/providerSettings.ts:15/20 向用户暴露 `settings.local.json` 文件路径；
  - apiClient.ts:3 兜底"操作失败，请重试。"不带操作名；apiClient.ts:51 可能直出后端字段名；
  - main.tsx:332 "若干个问题"；appText.ts:76/80 空洞的"处理中"；
  - main.tsx:1438 用原生 `window.alert` 直接拼后端原始错误；全仓约 8 处 `window.confirm`/`alert`；
  - SettingsModal.tsx:79-82 推理强度选项值为英文 low/medium/high/xhigh。
- `styles.css` ~3000 行单文件：无 `:root`/CSS 变量/design token，色值硬编码散布 100+ 行；数十个结构相似的卡片类选择器各自定义；仅 1 个响应式断点（980px）；仅一套硬编码深色主题。
- e2e 契约：21 条 Playwright 用例（`studio-ui-flow.spec.ts` 20 + `manual-fix-flow.spec.ts` 1），钉住文案字符串（如"最终交付已生成：2 个文件"、`passed`、`settings.local.json`）、~41 处 `data-testid`、CSS class（`.inline-status` 等）、行为（轮询刷新、长按删除、resume、100 行分页）。

## 1. 产品不变量（改前端不许破坏）

1. 九步向导、快速任务、公告流程三条主链路的每一步可达、可回退、可恢复。
2. 交付展示"最终译文 + 修改记录"两个文件的契约。
3. 正式翻译无 API key 时被阻断并给出可操作提示。
4. 中断的翻译任务显示"继续"而非新建。
5. 所有 `data-testid` 保留或与 e2e 同批更新，禁止先删测试后补。

## 2. 阶段划分

### 阶段 F1：提示语人话化（先做，独立可交付）

原则：用户读到的每句话必须回答"发生了什么 + 我现在能做什么"；不出现内部标识（状态枚举、字段名、文件路径、UUID、STEP 编号）。

- 批 1：文案基础设施。
  - 新建 `frontend/src/uiText.ts`：集中静态文案（按钮、空状态、确认框、操作名），导出 `runStatusLabel()`/`taskStatusLabel()` 覆盖全部英文状态值（queued/running/passed/failed/needs_input/canceled/delivered...）。
  - `apiClient.ts` 的 `sanitizeUserFacingError`/`apiErrorText` 增加可选 `operation` 参数，兜底文案变为"「{操作名}」失败：..."；调用点渐进传入。
- 批 2：修复问题清单（第 0 节列出的全部 + 执行时全文扫描补充），逐条替换；`TaskHistoryTable`/`RunDetail` 状态列走 `runStatusLabel`，UUID 折叠为短码+复制按钮。
- 批 3：原生 `window.alert`/`window.confirm`（~8 处）替换为应用内 `ConfirmModal`（复用现有 modal 样式，先在 main.tsx 内实现，阶段 F3 拆出）。
- 同批更新 e2e 断言（约 10 处文案断言 + confirm 交互改为点击 modal 按钮）。
- 验证：`npm run build` + 全量 e2e 22 条（含 manual-fix）。

### 阶段 F2：结构拆分（纯搬家，不改行为）

- 批 1：main.tsx 拆出组件文件——`components/modals/`（DeleteProjectModal、CancelAnnouncementTaskModal、NewProjectModal、FrequencyModal、新增 ConfirmModal）、`components/project/ProjectOverview.tsx`。
- 批 2：轮询收拢——新建 `hooks/usePolling.ts` 统一调度四套轮询（项目列表/项目快照/run 详情/公告任务），统一 `document.hidden` 检查、in-flight 去重（共享 promise）、AbortController；快速任务轮询保持独立但复用工具函数。
- 批 3：handler 按域收拢为 hooks——`hooks/useProjectActions.ts`、`useTranslationActions.ts`、`useGlossaryActions.ts`、`useAnnouncementActions.ts`；`App` 只剩状态编排和视图分发。
- 批 4：TranslationWizard 拆分——`translationWizard/steps/` 9 个 Step 文件 + `RunDetail.tsx`、`TaskHistoryTable.tsx`、`issueText.ts`。
- 每批拆完全量 e2e 必须绿；拆分批次内禁止顺手改文案或行为。

### 阶段 F3：性能

- run 活跃时暂停 6s 项目快照轮询（run 轮询结束时统一 `refreshCurrent`），消除重叠请求；2s run 轮询补 hidden 检查。
- 拆分后的热路径组件加 `React.memo` + 对应 handler `useCallback`：侧边栏项目列表、`TaskHistoryTable`、宽表、`ProjectOverview`。只做轮询触发重渲的路径，不全量包裹。
- `React.lazy` + `Suspense` 按需加载三大分支：`TranslationWizard`、`AnnouncementWorkflow`、`QuickTaskWizard`。
- run 历史表和项目动态列表加分页（复用 `assetTableState.ts` 的 100 行分页模式）。
- 验证：build 后记录 bundle 体积对比；e2e 全量；手工检查轮询请求数（DevTools network，活跃 run 期间 10 秒窗口内请求数应明显下降并记录数字）。

### 阶段 F4：视觉规范

- `styles.css` 顶部建 `:root` design token 层：色板（主紫/粉/绿/黄/红 + 中性色阶）、间距刻度（4px 网格）、圆角、字号。
- 渐进替换：先把出现频率最高的色值（紫系 #8b5cf6/#6366f1、绿 #10b981、红 #ef4444、黄 #f59e0b）收敛到变量；结构相似的卡片选择器抽公共类（`.surface-card` 基类 + 修饰类）。
- 补一档小屏断点（~640px），主要保证表格横向滚动和按钮不溢出。
- 不做：主题切换、重设计、组件库迁移。
- 验证：e2e 全量（class 契约不破坏）+ 手工目检每个 tab / 每步向导截图对比。

## 3. 验证与合并

- 每批：`npm --prefix frontend run build` + 受影响 e2e；每阶段末：全量 e2e 22 条 + 后端全量 pytest（防止前端契约测试牵连）。
- 阶段 F1 单独合并推送（用户立刻受益）；F2-F4 每阶段一个分支，worktree 隔离（TEMP/端口隔离规则照旧）。
- 与多人化计划的衔接：F1 可与多人化后端阶段并行（文件不相交）；多人化的"活跃任务面板"前端工作在本计划 F2 完成后做（复用拆分后的结构）。

## 4. 完成标准

- [ ] 全部用户可见文案无内部标识直出（状态枚举/字段名/文件路径/UUID/STEP 编号），抽查 20 条场景提示均能回答"发生了什么+能做什么"。
- [ ] 无原生 alert/confirm。
- [ ] main.tsx ≤ 600 行、TranslationWizard.tsx ≤ 500 行，无行为回归（e2e 22/22）。
- [ ] 活跃 run 期间 10 秒窗口 API 请求数较基线下降 ≥ 40%（记录前后数字）。
- [ ] 三大分支懒加载生效（初始 bundle 减小，记录前后体积）。
- [ ] styles.css 有 token 层且高频色值全部走变量；980px/640px 两档断点。
- [ ] 每阶段合并前全量 e2e 绿，最终 Tier C 全绿。

## 5. 风险

- e2e 文案断言与实现不同批改 → 规则：同一提交内完成，CI 即验证。
- 拆分引入隐性行为变化（闭包捕获、effect 依赖）→ 拆分批次禁止改逻辑，review 时 diff 只允许移动和 import 变化。
- memo/useCallback 过度使用增加复杂度 → 只处理列出的热路径，其余不动。
