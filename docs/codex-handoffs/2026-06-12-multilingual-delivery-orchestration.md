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
