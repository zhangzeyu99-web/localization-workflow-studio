# 术语提炼工作流

## 目标

从完整翻译语言表中稳定提炼出：

- 高频重复词
- 易混淆近义词
- 需要全局统一的系统词
- 需要保留第二套适配译法的术语

最终形成可交付的 `ID / CN / EN / EN2` 术语表。

## 适用场景

- 游戏出海本地化
- 新版本语言表梳理
- 活动、付费、战斗系统术语统一
- 翻译供应商切换前的术语基线搭建

## 标准流程

### 1. 输入审计

先确认：

- 原文列是否稳定，默认是 `cn`
- 目标语言列是否稳定，默认是 `en`
- `ID` 是否可追溯
- 是否存在大量占位符、富文本标签、测试串、活动临时文案

### 2. 项目审查与风格提示词

扫描完整语言包时，同步生成项目审查文件，用于指导后续翻译风格：

- 根据词条内容推断题材方向，例如战斗/RPG、基地经营、活动商业化、社交公会、飞行射击、末日生存、剧情叙事
- 可合并额外输入，例如游戏资料、世界观设定、已有翻译文本、术语表、截图文件名、人工图片观察备注
- 根据项目内容判断翻译重点，例如 UI/玩法需要移动端精简，剧情对话需要自然、地道、通顺
- 根据已有英文覆盖率判断是否应优先尊重历史译文和手动适配
- 输出 `*_project_brief_YYYYMMDD.md`，只保留 `AI 生成的专属翻译提示词` 和 `项目元信息`

常用命令：

```bash
python scripts/extract_glossary.py /path/to/language_table.xlsx \
  --project-name "Project Name" \
  --project-brief-output /path/to/project_brief.md \
  --project-material /path/to/game_design.md \
  --project-note "截图显示核心 UI 是深色科幻机库和战机强化界面。" \
  --translation-prompt-output /path/to/translation_prompt.txt
```

补充资料处理口径：

- `txt / md / json`：按段落抽取项目描述
- `csv / tsv / xlsx`：优先按语言表/资料表表头抽取；没有标准表头时拼接每行非空文本作为资料片段
- 图片：默认使用文件名和目录名作为题材线索；如需利用画面内容，把人工观察或 OCR 文本写进 `--project-note`

如果某次只跑术语、不需要项目审查，可加：

```bash
python scripts/extract_glossary.py /path/to/language_table.xlsx \
  --no-project-brief
```

项目审查是语言表推断结果，不替代正式项目设定；如果发行地区、人称、世界观或品牌语气已有明确规范，应以项目规范为准。对含剧情的休闲项目，默认提示词会把游戏内容/UI 和剧情对话拆开：前者精简适配移动端，后者按美剧式自然对白处理。

### 3. 原文提取

术语只从原文列抽取，不从译文反推。原因：

- 原文是术语主键
- 同一术语可能被译为不同英文
- 译文只能用于判断是否漂移，不适合拿来定义术语边界

### 4. 候选筛选

优先保留：

- 高频出现
- 多系统复用
- 玩家操作强相关
- 数值、资源、稀有度、玩法、按钮词

优先排除：

- 整句描述
- 一次性剧情文案
- 测试串
- 嵌入图片或复杂富文本的整段内容

### 5. 英文对齐

用英文列做两件事：

- 找示例英语 `EN`
- 检查实际译文是否出现另一套稳定用词 `EN2`

如果语言表还没有英文列，则先启用源文-only 模式，只提取 `CN` 候选并保留 `ID / CN / EN / EN2` 结构。后续拿到人工确认或翻译结果后，再用回灌脚本补齐规则层。

源文-only 项目建议按状态分阶段交付：

- `项目名-已提取-YYYYMMDD.xlsx`
- `项目名-预翻译-YYYYMMDD.xlsx`
- `项目名-已分类-YYYYMMDD.xlsx`
- `项目名-已审校-YYYYMMDD.xlsx`
- `项目名-已回灌-YYYYMMDD.xlsx`

分类整理版主表使用 `ID / CN / EN / EN2 / 分类`，并将 `分类` 放在最后一列。同类术语应连续排列，便于翻译、LQA 和术语管理员筛选。完整复盘见 [source-only delivery retrospective](source-only-delivery-retrospective.md)。

### 5.1 版更公告按需术语提取

当输入是版更公告、活动公告、更新说明等长文本时，不需要重新导出完整术语表。可以用公告文本反查完整语言表，只输出公告实际用到的术语行，并保留完整语言表中的全部语言列：

```bash
python scripts/extract_glossary.py /path/to/language_table.xlsx \
  --announcement-material /path/to/update_notice.docx \
  --announcement-output /path/to/update_notice_terms.xlsx
```

公告命令未显式传入 `--output`、`--final-output`、`--project-brief-output` 或项目资料参数时，会自动跳过完整术语明细、最终术语表和 project brief，只生成公告术语表。

脚本会扫描语言表前若干行自动定位表头；常见导出型总表如 `索引ID / 内容 / 中文，用于导出...` 会自动映射为 `ID / CN / EN`，不需要先手动删除导出元数据行。对于 `["活动名"]`、`["活动名", "#色值"]`、嵌套帮助列表标题等非规范单元格，也会提取干净术语和对应译文。

公告资料支持 `docx / txt / md / json / csv / tsv / xlsx`，可以重复传入：

```bash
python scripts/extract_glossary.py /path/to/language_table.xlsx \
  --announcement-material /path/to/update_notice.txt \
  --announcement-material /path/to/event_notice.xlsx \
  --announcement-output /path/to/announcement_terms.xlsx \
  --announcement-min-hit 1
```

多语言公告术语表使用显式语言码传入，输出一张合并后的 `Glossary`，并在同一文件增加 `SentenceTemplates`：

```bash
python scripts/extract_glossary.py \
  --language-table EN=/path/to/language_en.xlsx \
  --language-table FR=/path/to/language_fr.xlsx \
  --announcement-material /path/to/update_notice.txt \
  --announcement-output /path/to/announcement_terms.xlsx
```

`SentenceTemplates` 用于保存公告命中的官方完整句式和相似句证据。翻译时固定优先级为：官方完整句式、官方相似句表达、单个术语、模型自行翻译。完整句式中的 `<@1>`、`{0}`、`{0,Num}`、`%s`、`%d` 等占位符会按公告实际值回填；无法安全对应时保留原模板并给出警告。

部分语言包使用 `中文key` 作为第一列表头，紧邻的第二列直接保存译文但表头为空。通过 `--language-table LANG=path` 传入这类文件时，脚本会自动识别该相邻译文列，并在原表没有 ID 时使用 `工作表名:行号` 作为追溯标识。

多语言合并以第一个 `--language-table` 作为术语和句式主源，其余语言表只补齐相同 CN 的目标语，避免次要语言包的额外工作表把泛词或单语句式带入交付表。

如果已经有翻译后的公告，可重复传入 `--translated-material LANG=path`。脚本会检查命中的官方完整句式是否被沿用；不一致时命令仍返回成功，但控制台和 validation Markdown 会记录严重警告：

```bash
python scripts/extract_glossary.py \
  --language-table EN=/path/to/language_en.xlsx \
  --language-table TH=/path/to/language_th.xlsx \
  --announcement-material /path/to/update_notice.txt \
  --translated-material EN=/path/to/update_notice_en.docx \
  --translated-material TH=/path/to/update_notice_th.docx \
  --announcement-output /path/to/announcement_terms.xlsx
```

提供 `--translated-material` 时，即使未显式指定 `--announcement-validation-output`，也会自动生成 `*_announcement_validation_YYYYMMDD.md`。未提供翻译成品时，官方句式 QA 状态为 `not_run`，不能视为已校验。

AI 补充层用于提高召回率，但不把完整语言包放进上下文。packet 按完整句式、相似句证据、已命中术语和未覆盖文本的顺序提供精简信息。

Codex 线程内执行术语任务时，标准流程是先生成 packet，由当前 Codex 模型直接做漏词补充、句内术语拆分和置信检查，再把结构化 response 回填给脚本：

```bash
python scripts/extract_glossary.py /path/to/language_table.xlsx \
  --announcement-material /path/to/update_notice.txt \
  --announcement-output /path/to/announcement_terms.xlsx \
  --project-name "Project Name" \
  --ai-supplement \
  --ai-supplement-provider packet \
  --ai-supplement-packet-output /path/to/update_notice_ai_packet.json
```

Codex 读取 packet 后生成 `/path/to/ai_response.json`，再回填。只有公告中出现、具备语言表证据、置信度不低于 medium 的补充术语会进入主 Excel；其他候选只写 sidecar 报告：

```bash
python scripts/extract_glossary.py /path/to/language_table.xlsx \
  --announcement-material /path/to/update_notice.txt \
  --announcement-output /path/to/announcement_terms.xlsx \
  --project-name "Project Name" \
  --ai-supplement \
  --ai-supplement-provider file \
  --ai-supplement-response /path/to/ai_response.json \
  --ai-supplement-report-output /path/to/ai_supplement_report.md
```

如果要脱离 Codex 线程自动跑，也可以设置 `OPENAI_API_KEY` 并使用 `--ai-supplement-provider openai` 或 `auto`。`--ai-supplement-provider` 支持 `auto / openai / file / packet`；`auto` 的优先级是：`--ai-supplement-response` 文件、`OPENAI_API_KEY` 自动调用、packet-only fallback。

Codex 线程内执行检查清单见 [codex-thread-ai-supplement.md](codex-thread-ai-supplement.md)。后续在 Codex 线程里跑术语提取时，脚本结果不是最终步骤，必须再由 Codex 做一次补充检查。

处理口径：

- 先在本地语言表中匹配官方完整句式；完整句未命中时才提供相似句证据和术语级候选
- 用中文公告文本做精确包含匹配，按公告首次出现位置排序，同位置长词优先
- AI 补充只用于漏词补充、句内术语拆分和置信提示，不直接决定标准译文
- 输出 `Glossary` 与 `SentenceTemplates` 两个 sheet；`Glossary` 的列结构和顺序保持不变，模板页记录匹配优先级、类型、官方中文模板和各语言译文
- 多语言模式输出 `ID / CN / EN / FR...`，以 CN 精确合并；同一 CN 多个 ID 时使用第一个语言表的首个命中 ID
- 低价值通用词只降级排序，不默认删除，避免漏掉固定 UI 译法
- 默认只生成术语译文交付表；如需内部审计，可显式传 `--announcement-validation-output /path/to/announcement_validation.md` 生成 validation Markdown
- 默认只输出有英文译文的术语；需要保留空 EN 候选时，加 `--include-empty-final-terms`
- `.docx` 只读取正文文本，不读取批注、修订记录或图片 OCR

### 6. 示例与手动适配拆分

拆分原则：

- `示例`
  和标准英语一致，或只是基于标准英语的短语扩展
- `手动适配`
  在实际短句里出现了稳定、可复用、与标准英语不同的另一套用词

示例：

- `Registration` 和 `Registration Countdown`
  仍算示例同族，不拆出 `EN2`
- `Registration` 和 `Sign Up`
  是两套不同译法，应写入 `EN2`

### 6.1 规则层与观察层反哺

如果某个术语已经被人工确认：

- 优先使用 `approved_en`
- 优先使用 `approved_en2`
- 如果 `block_en2 = true`，则不再自动派生 `EN2`

如果某个术语在历史跑表里已经多次出现：

- 合并 `observed_exact_candidates`
- 合并 `observed_example_usages`
- 合并 `observed_manual_adaptations`

这样可以把一次人工判断沉淀为规则层，把后续运行的真实观察沉淀为自动学习层。

### 7. 风险判定

以下情况优先列为高风险：

- 同一原文对应多个英文版本
- 稀有度、资源、数值、按钮操作词
- 高命中但大多以内嵌形式出现
- 实际短句里存在手动适配

### 8. 最终交付

最终表只保留：

- `ID`
- `CN`
- `EN`
- `EN2`

其中：

- `EN` 是标准示例译法
- `EN2` 只在替代译法稳定成立时填写，否则留空

## 自动回归

每次优化提取逻辑后，应使用 harness 跑 fixture：

```bash
python scripts/run_glossary_harness.py \
  fixtures/core_regression.json \
  fixtures/observation_feedback_regression.json \
  fixtures/announcement_lookup_regression.json \
  fixtures/announcement_ai_supplement_regression.json \
  fixtures/announcement_sentence_templates_regression.json
```

通过后再跑真实语言表。

## 人工确认回灌

人工确认完 `ID / CN / EN / EN2` 交付表后，应尽快回灌到规则层：

```bash
python scripts/import_curated_glossary.py /path/to/final_glossary.xlsx \
  --curated-rules data/experience/curated_terms.json
```

这样下一次跑表时，标准 EN、稳定 EN2 和明确禁止 EN2 的术语都会直接继承。

## 推荐复核顺序

1. 稀有度
2. 数值属性
3. 操作按钮
4. 活动和付费系统
5. 非空 `EN2`

## 版本维护建议

- 每次大版本或新活动上线前重跑一遍
- 每月回顾一次 `EN2` 是否仍有保留价值
- 将争议项单独列入 review 列表，不直接写死进术语库

## 术语价值筛选与交付规范补充

交付术语表只保留可复用、可约束后续翻译一致性的词条。以下内容默认不进入最终术语表：

- `技能名/系统名 + 数值效果` 的组合短句，例如 `冰封扩散伤害提高`、`基础属性提高`、`持续时间增加`。
- `等级/颜色/投放批次 + 武器/装备` 的配置型道具名，例如 `10级红色愤怒武器`、`活动投放40级武器`、`随机红色装备`。
- 奖励、状态、提示类短句，例如 `排行奖励`、`获得奖励`、`后解锁`、`已领取`。
- 带变量、加号、占位符或明显程序配置语义的短语，例如 `成员上限+1`、`{0}`、`#{...}`。

以下内容可以保留：

- 职业、系统名、玩法名、副本名、技能名、装备/道具基础名、属性名、品质阶梯、怪物/角色名。
- 高频动作词可作为固定译法保留，分类为 `动作`，例如 `获得`、`获取`、`领取`、`使用`、`激活`、`解锁`、`购买`、`兑换`、`前往`、`重置`。动作词用于统一 UI 与系统提示译法，不等同于保留所有普通动词。

交付表默认列结构：`ID / CN / 目标语言主译 / 分类`。目标语言只保留主译，不写多译法或备选列；审计信息、验收报告和中间文件不作为默认交付物。
