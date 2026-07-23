# 官方句式模板层实施计划

> **执行要求：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，按勾选项逐步实施。

**目标：** 为公告术语输出增加官方句式模板层，并在用户提供的译文没有沿用官方完整句式时给出警告。

**架构：** 保持现有 `Glossary` 不变，新增 `SentenceTemplates`。新匹配模块读取保留占位符的语言表原始单元格，先匹配完整模板，再提供相似句证据，将公告实际值回填进官方译文，并校验可选的翻译成品。CLI 只编排本仓库能力，不修改完整术语提取和工作台仓库。

**技术栈：** Python 3.11+、openpyxl、unittest/pytest、现有 fixture harness。

## 全局约束

- 只修改 `D:\codex\glossary-extraction-workflow`。
- 保持现有 `Glossary` 的列、内容和顺序不变。
- 优先级固定为官方完整模板、官方相似语境、单个术语、模型兜底。
- 译文不一致属于严重警告，但不能改变 CLI 的成功退出码。
- 不修改或暂存主工作区的 `data/experience/observed_terms.json`。
- 不更新 `localization-workflow-studio`。

---

### 任务 1：匹配核心

- [x] 为 `<@n>` 捕获回填、标点统一、上下文属性短语、相似证据和不安全占位符映射增加失败测试。
- [x] 在 `glossary_extraction/sentence_templates.py` 实现保留占位符的标准化和精确模板匹配。
- [x] 实现稳定的相似语境排序，每个重合表达最多两条。
- [x] 运行聚焦测试直至通过。

### 任务 2：工作簿与 AI 优先级接入

- [x] 增加集成失败测试，要求 `Glossary` 不变且稳定输出 `SentenceTemplates`。
- [x] 从单表和多语言表读取并合并句式候选。
- [x] 将已套值的完整译文和相似整句证据写入第二个工作表。
- [x] 在 AI 补充包中把完整句式和相似证据放在单个术语之前。
- [x] 运行工作簿和 packet 聚焦测试直至通过。

### 任务 3：译文警告门禁

- [x] 为 `--translated-material LANG=path`、只警告不阻断、完整沿用成功和自动校验报告增加 CLI 失败测试。
- [x] 从支持的本地材料中读取完整译文，检查官方完整句式。
- [x] 在报告和控制台增加命中、不一致及无法校验占位符计数。
- [x] 运行 CLI 聚焦测试直至通过。

### 任务 4：文档与发布验证

- [x] 更新工作流文档和术语线程 handoff；README、VERSION、CHANGELOG 保持不变。
- [x] 运行完整 pytest、全部既有 harness、新增模板 fixture、输出质量检查和真实四语言本地冒烟测试。
- [x] 审查差异，只暂存本功能文件，提交并推送 `agent/official-sentence-templates`。
