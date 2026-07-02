# Localization Workflow Studio 协作规则

## 翻译执行边界

- 正式翻译默认使用项目上下文、术语表、历史已验收交付和 AI provider；除非用户明确要求，不使用 Google Translate、`deep_translator`、`googletrans` 或浏览器机翻做初译。
- 所有翻译/本地化交付必须区分结构 QA 和逐句审校；未完成逐句审校时不得称为“已校对”。
- 结构 QA 必查目标列/文件完整、源行对齐、占位符和程序标签保留、目标文本无中文残留、非预期全角/非 ASCII 残留、未请求语言列不被写入。
- 逐句审校必查漏译、误译、术语漂移、游戏/UI 语境、英文自然度、数字/日期/单位/范围保留和同类句式一致性。

## 大文本多语言任务

- 产品内长文本/多语言工作流以 `backend/app/workflow/multilingual.py` 和 `backend/app/workflow/translation_orchestrator.py` 为准，Codex/Agent 不是产品运行依赖。
- Agent 处理本地大 workbook/DOCX 任务时，使用 `workflow/localization/scripts/run_large_text_multilingual_runner.py` 生成 manifest，用 `run_large_text_multilingual_gate.py` 做 preflight/cache-lint/apply-dry-run/readback-gate，用 `run_large_text_multilingual_retro.py` 做复盘。
- API 负责语义翻译；本地 gate 只做可确定检查，不把 Google 或外部机翻作为初译来源。
- 深度逐句校对只有在用户明确要求时启用 subagent；subagent 只能输出 JSONL 审校建议，不直接写最终文件，主控合并后必须重跑结构 QA。
- 最终交付目录只保留最终文件和 QA 摘要，不混入 manifest、workpack、response、jsonl、log 等过程文件。
