# Codex 线程内 AI 补充检查

本文档定义在 Codex 线程里执行术语提取任务时的标准动作。目标是让 Codex 模型参与漏词补充、句内术语拆分和交付表检查，但不把完整语言包直接放进模型上下文。

## 适用范围

- 完整语言表术语提取：从项目语言表、翻译需求、术语页、项目 brief 中提取交付术语表。
- 公告按需术语 lookup：从完整语言表反查公告实际需要的术语译文。

## 完整语言表术语提取

脚本先产出基础术语表。Codex 线程随后必须做一次 AI 补充检查：

1. 读取项目资料、翻译需求 sheet、术语 sheet、project brief 和脚本术语表结果。
2. 只做有限抽样和关键词扫描，不把完整语言表整表贴入上下文。
3. 检查是否遗漏世界观、系统名、建筑/房间、活动、道具、角色身份、UI 固定词和高频易混词。
4. 对新增项必须能回溯到源文件中的中文文本或项目资料；不能凭空编词。
5. 按 CN 去重，补充到交付术语表底部或按用户要求归类整理。
6. 主表保持用户要求的列结构，例如 `ID / CN / EN / EN2` 或 `ID / CN / EN / EN2 / 分类`。

## 公告术语 lookup

公告任务使用脚本生成精简 packet，再由 Codex 线程直接生成 response：

```bash
python scripts/extract_glossary.py /path/to/language_table.xlsx \
  --announcement-material /path/to/update_notice.txt \
  --announcement-output /path/to/announcement_terms.xlsx \
  --ai-supplement \
  --ai-supplement-provider packet \
  --ai-supplement-packet-output /path/to/notice_ai_packet.json
```

Codex 读取 `notice_ai_packet.json` 后，只基于以下内容判断：

- `announcement_text`
- `matched_terms`
- `evidence_rows`
- `project_name`

Codex 生成结构化 `ai_response.json`，再回填：

```bash
python scripts/extract_glossary.py /path/to/language_table.xlsx \
  --announcement-material /path/to/update_notice.txt \
  --announcement-output /path/to/announcement_terms.xlsx \
  --ai-supplement \
  --ai-supplement-provider file \
  --ai-supplement-response /path/to/ai_response.json
```

## Codex 判断规则

- 只补公告或项目资料中实际出现的术语。
- 优先补系统名、活动名、玩法名、道具名、角色名、建筑/房间名、世界观专名。
- 可从句子中拆出术语，例如从“开启星界裂隙挑战”拆出“星界裂隙”。
- 新增进主表必须有语言表译文证据或用户提供的明确译文依据。
- 无证据、低置信、推断译名只进入说明或报告，不写入主交付表。
- 项目名没有标准译文时，必须提醒用户补充，不在主表加占位行。

## 交付口径

- 用户只要交付表时，只交付 Excel；报告、packet、response 作为中间文件留本地或清理。
- 最终回复只说明交付表路径、补充数量、验证结果和必要风险。
