# 深度逐句校对与 subagent 工作流

## 触发条件

默认翻译任务不启用深度逐句校对。只有用户明确提到“逐句校对”“深度校对”“完整校对”“全量审校”“逐行审校”“LQA 深校”等表达，或任务被标记为高风险全量审校时，才启用本流程。

未触发时执行基础校对：术语命中、结构 QA、占位符/数字/乱码/中文残留、未请求语言列保护、最终读回验证和高风险抽查。

## 主控职责

- 读取源文件、术语表、历史交付和项目 brief。
- 生成待审 workpack，并按语言、风险和文本长度拆分。
- 跑结构 QA，标记高风险行。
- 分派 subagent 校对包。
- 合并 subagent 建议，执行二次纠偏和确定性 QA。
- 写回 workbook/docx，最终读回和交付。

## Subagent 职责

- 只审查分配给自己的行包，不自行扩大项目目录或语言范围。
- 逐句判断当前译文是否需要修改。
- 只输出 JSONL/JSON 建议，不直接改 workbook/docx，不改术语表，不写最终交付。
- 遇到上下文不足时返回 `NEEDS_CONTEXT` 或 `BLOCKED`，由主控补齐上下文或拆小任务包。

## 分片策略

- 高风险行全量进入深度审校。
- 低风险行默认抽样 10%-20%，除非用户明确要求全量逐句。
- 长文本每包 1-5 行，普通文本每包 30-80 行，UI 短文本可更大但必须保留完整上下文。
- 每个审校包使用新 subagent，不复用主线程长历史，避免上下文污染和窗口膨胀。

## 风险标签

- `long_text`: 单元格超过 300 中文字符或包含多段规则。
- `placeholder_dense`: 占位符、程序标签、数字较多。
- `term_dense`: 命中 3 个以上术语。
- `tm_conflict`: 历史译法和术语表冲突。
- `qa_failed_once`: 结构 QA 曾报错或被修复。
- `model_uncertain`: 初译模型标记不确定。
- `user_focus`: 用户点名要求重点检查。

## Subagent 输入契约

```json
{
  "task_id": "project_lang_batch_001",
  "project": "项目名",
  "target_lang": "EN",
  "style_guide": "简短游戏 UI；保留程序 token；不使用外部机翻",
  "glossary_policy": "术语命中是约束，不做机械替换；正文允许自然语境变体",
  "rows": [
    {
      "id": "10001",
      "source": "中文源文",
      "current_translation": "Current translation",
      "translation_memory": "可选历史译法",
      "term_hits": [{"cn": "公会", "target": "Guild", "note": "系统名"}],
      "placeholders": ["{num}", "[v0]"],
      "numbers": ["10"],
      "risk_flags": ["term_dense", "placeholder_dense"]
    }
  ]
}
```

## Subagent 输出契约

```json
{
  "id": "10001",
  "lang": "EN",
  "decision": "change",
  "current": "Current translation",
  "suggested": "Suggested translation",
  "reason": "术语和语义更准确",
  "severity": "medium",
  "placeholder_ok": true,
  "number_ok": true
}
```

`decision` 只能是 `keep`、`change`、`flag`。`flag` 表示不确定，必须由主控复核。主控接受任何建议前，都必须重新跑结构 QA 和读回验证。

## 交付要求

- QA 摘要记录 deep proofread trigger、subagent batch 数、审校行数、建议修改数、最终应用数、回退数和 hard blocker 数。
- 最终回复必须区分结构 QA 和逐句审校是否完成。
- 如果未启用 subagent，只能说完成基础校对或高风险抽查，不能称为全量逐句校对。
