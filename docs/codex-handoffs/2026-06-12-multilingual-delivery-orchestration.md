# 多语言翻译编排与合并交付上下文

## 当前结论
- 工作台当前支持多选目标语言，但 Step 7/8 实际仍按当前语言单独执行。
- 普通语言包最终交付目前按单个 run_id 生成单语言 final/changes，不会自动合成 EN/KR/JP 多语言完整文档。
- 公告任务已有多语言 ZIP 交付，但普通语言包还没有“多语言合并最终交付”。

## 用户确认的目标
- 翻译流程应该是：用户在目标语言处多选后，由工作台按语言逐个跑翻译、QA、归档、交付准备，不要求用户反复切步骤。
- 交付步骤应该合成一个完整多语言文档。
- QA 校对技术仓库原本已实现合并交付，应优先复用该实现或对齐其产物规则。

## 当前需要核实
- `D:\project\localization-workflow-project` 中 QA/交付 harness 如何将多语言结果合成完整文档。
- 工作台内置副本 `workflow/localization` 是否已经同步了该能力。
- 工作台后端 `backend/app/workflow/delivery.py` 是否需要新增普通语言包 ALL 合并交付入口。
- 前端 Step 6/7/8 是否要从“手动切当前语言”改为“选中语言队列自动执行”。

## 不应改变
- 本地终端 + 局域网工作方式保持可用。
- 单语言 run 机制可保留，作为底层可恢复子任务。
- 现有单语言交付文件继续保留，新增多语言合并交付不能破坏旧下载。

## 下一步
1. 查技术仓库多语言交付实现。
2. 查工作台内置 workflow 是否已有对应脚本/接口。
3. 对齐差距，写改造计划：多语言任务队列 + 合并交付文件。

## 2026-06-12 技术仓库核实结果

### 工作台现状
- `frontend/src/main.tsx` 保留 `selectedLanguages` 多选状态，但创建翻译 run 仍使用 `selectedLanguage` 单语言。
- `frontend/src/main.tsx` 的交付请求仍是 `/api/projects/{id}/delivery-package?run_id=...`，一次只交付一个 run。
- `backend/app/workflow/delivery.py::build_delivery_package(project_id, run_id)` 从 `list_project_deliverables()` 中选择一个 run 生成 final/changes，缺少跨语言合并。
- `frontend/src/components/translationWizard/TranslationWizard.tsx` Step 7/8 文案和状态也说明当前需要先完成当前语言，再切换下一种语言。

### 技术仓库现状
- `D:\project\localization-workflow-project\process_language.py::_build_result_full()` 会复制完整原表，并只把当前语言列的修复译文回填进去。
- `process_language.py::write_outputs()` 输出 `result_{lang}.xlsx` / `report_{lang}.xlsx`，`result` 中保留完整表结构，可作为多语言合并底稿。
- `process_language.py::ensure_final_delivery_ready()` 有最终 hard gate，但这是单语言成品检查，不等于工作台多语言合并编排。
- `utils/announcement_docx_harness.py` 已经是多语言交付模型：prepare 生成多语言列中转表，apply 同时输出各语言 DOCX，deliver 汇总成交付目录。
- `workspace_runner.py --lang auto` 会发现多个语言任务并逐个处理，但它是 workspace 级命令行循环，不是工作台 UI 的项目内自动编排。

### 推荐落地边界
- 不推翻单语言 run；新增“多语言父任务/队列”负责编排多个单语言 run。
- Step 6 选择多个语言后，Step 7 一键按队列执行：EN -> KR -> JP...；每个语言独立断点续跑。
- Step 8 一键按队列 QA；每个语言独立 QA/修复/归档，失败只卡对应语言。
- Step 9 新增普通语言包 ALL 合并交付：以原始 workbook 为底稿，按语言把各 run 的 final workbook 对应语言列回填，生成一个完整多语言 final workbook；同时保留每语言 changes/report。

## 2026-06-12 断点交接

### 当前 Git / 工作区状态
- 当前分支：`master`，本地领先远程 1 个提交。
- 本轮多语言编排尚未完成；目前只落了两个后端预备改动：
  - `backend/app/db.py`：新增 `merged_delivery_workbook`、`merged_delivery_summary` 两类交付 artifact 角色映射。
  - `backend/app/schemas.py`：新增 `MultilingualQueueRequest` 请求结构。
- 当前还未新增队列服务、路由、合并交付实现、前端按钮、测试。
- 当前未纳入本计划的无关未跟踪文件：`docs/PRODUCTION_DEPLOYMENT_PLAN.md`，暂不混入多语言编排提交。

### 本轮继续实现的最小闭环
1. 后端新增普通语言包多语言编排层：按选中语言创建/复用单语言 translation run，顺序执行，失败语言不影响其他语言。
2. 后端新增多语言 QA 编排：按选中语言创建/复用 QA run，已通过语言跳过。
3. 后端新增普通语言包 ALL 合并交付：以原始语言表为底稿，将已通过或已允许交付的语言列合并到同一个 workbook。
4. 前端 Step 7/8 从“当前语言单独跑”改成“多语言队列卡片 + 一键启动队列”。
5. 前端 Step 9 增加“生成多语言合并交付”，保留单语言下载。

### 需要避免的误区
- 不改公告任务流程。
- 不把多语言合并成一个模型请求；仍是多个单语言 run。
- 不修改现有 `/api/runs` 单语言接口行为，避免回归快速任务、单语言任务和旧 E2E。
- 不把失败语言强行写入合并交付；失败语言只进入 QA 摘要。

### 旁路待处理问题（不混入本计划，除非用户要求）
- 术语表导入后状态显示“已导入”但概览术语表仍为空：疑似前端刷新/宽表来源或导入字段识别问题。
- 删除项目提示 `project not found`：疑似选中项目已被删除、列表状态滞后或删除接口/当前项目状态不同步。

### 下一步执行顺序
1. 补 `backend/app/workflow/multilingual.py`，先实现状态查询、子 run 创建/复用、队列启动。
2. 补后端路由：`/multilingual/status`、`/multilingual/translate/start`、`/multilingual/qa/start`、`/delivery-package/merged`。
3. 补合并交付实现和后端单测。
4. 接前端 Step 7/8/9。
5. 跑后端测试、前端 build/E2E、禁机翻扫描。


## 2026-06-12 完成收口

### 已落地
- 新增普通语言包多语言编排后端：按目标语言创建/复用单语言 translation run，后台队列逐个执行。
- 新增多语言 QA 编排后端：按目标语言创建/复用 QA run；没有翻译产物且原表该语言未 ready_for_qa 时不会误建 QA。
- 新增普通语言包 ALL 合并交付：以原始语言表为底稿，将已完成/可交付语言列合并回同一 workbook，并生成 QA 摘要。
- 前端 Step 7 改为多语言翻译队列入口；Step 8 改为多语言 QA 队列入口；Step 9 增加“多语言合并交付”。
- 保留单语言 run、单语言交付、快速任务、公告流程，不改变旧接口行为。

### 验证结果
- `python -m pytest -q`：138 passed。
- `python -m compileall -q backend workflow`：通过。
- `python -m ruff check backend/app backend/tests --select E9,F`：通过。
- `cd frontend; npm run build`：通过。
- `cd frontend; npm run e2e -- --workers=1`：18 passed。
- 禁 Google/机翻扫描未新增命中；既有 provider 兼容路径里仍存在 `chat/completions` 字符串，不属于本轮新增。

### 仍需后续单独处理
- `docs/PRODUCTION_DEPLOYMENT_PLAN.md` 仍是无关未跟踪文件，未纳入本轮。
- 工作区还包含前面未提交的术语导入刷新、项目删除状态同步等修复；它们与本轮一起待提交或另拆提交。
