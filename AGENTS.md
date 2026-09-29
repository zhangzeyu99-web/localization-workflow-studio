# Localization Workflow Studio 协作规则

## 工作流目录同步关系（先读这条再改代码）

- `workflow/localization` 和 `workflow/glossary` 是**同步产物**，禁止直接修改；两者的维护源分别是：
  - 本地化工作流（翻译校对/大文本）：`D:\project\localization-workflow-project`（github.com/zhangzeyu99-web/localization-workflow）
  - 术语提取（项目 brief/术语提取）：`D:\codex\glossary-extraction-workflow`（github.com/zhangzeyu99-web/glossary-extraction-workflow）
- 修改流程：改源仓库 → 源仓库受影响行为验证通过并提交 → 在 studio 根跑 `python scripts/sync_workflow_sources.py <localization|glossary|all>`（复用既有同步入口，不额外计算目录或文件哈希）→ 仅验证受影响行为。
- 上游测试只在维护源保留，不同步进 `workflow/*/tests`；工作台保留自己的精简集成测试。修改 `process_language.py`、`run_quality_harness.py`、`run_translation_harness.py` 等 subprocess 接口时，运行受影响的工作台用例，不重复跑上游整套。
- 细则见各目录 `SYNC.md`；每个入口脚本的 `Boundary:` docstring 标注 product-runtime / agent-only 归属。

## 翻译执行边界

- 独立翻译质量评估与深校复盘先读 `docs/INDEPENDENT_TRANSLATION_QUALITY_EVALUATION.md`，核实维护源与同步副本的实际生效状态。结构门禁和修改量不得作为语义质量证明。

- 正式翻译默认使用项目上下文、术语表、历史已验收交付和 AI provider；除非用户明确要求，不使用 Google Translate、`deep_translator`、`googletrans` 或浏览器机翻做初译。
- 所有翻译/本地化交付分别报告基础校对、结构 QA 和深度逐句审校的完成状态；未完成深度逐句审校时不得声称完成逐句审校。基础校对须包含术语和成品读回，不以结构门禁代替语义判断。
- 结构 QA 必查目标列/文件完整、源行对齐、占位符和程序标签保留、目标文本无中文残留、非预期全角/非 ASCII 残留、未请求语言列不被写入。
- 逐句审校必查漏译、误译、术语漂移、游戏/UI 语境、英文自然度、数字/日期/单位/范围保留和同类句式一致性。

## 大文本多语言任务

- 产品内长文本/多语言工作流以 `backend/app/workflow/multilingual.py` 和 `backend/app/workflow/translation_orchestrator.py` 为准，Codex/Agent 不是产品运行依赖。
- Agent 处理本地大 workbook/DOCX 任务时，使用 `workflow/localization/scripts/run_large_text_multilingual_runner.py` 生成 manifest，用 `run_large_text_multilingual_gate.py` 做 preflight/cache-lint/apply-dry-run/readback-gate，用 `run_large_text_multilingual_retro.py` 做复盘。
- 深度逐句校对只有在用户明确要求时启用 subagent；subagent 只能输出 JSONL 审校建议，不直接写最终文件，主控合并后必须重跑结构 QA。
- 最终交付目录只保留最终文件和 QA 摘要，不混入 manifest、workpack、response、jsonl、log 等过程文件。
