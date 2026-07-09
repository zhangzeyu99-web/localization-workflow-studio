# 术语提取执行线程 Handoff

本文档用于新建或接管“术语提取执行线程”。该线程只负责术语提取工作流的原始能力，不负责工作台产品更新。

## 1. 线程定位

本线程是游戏出海本地化术语提取专用执行线程。

负责：

- 完整语言表术语提取
- source-only 中文术语提取
- `ID / CN / EN / EN2 / 分类` 术语表整理
- 公告术语 lookup
- 多语言公告术语合并
- AI supplement packet / response 接口
- 项目 brief / translation prompt 生成，仅限术语提取流程附带能力
- 本仓库 README / CHANGELOG / VERSION / docs / tests / fixtures / harness 维护

不负责：

- 工作台前端、后端、部署、数据库、任务队列
- `D:\codex\localization-workflow-studio` 的产品更新
- 4399 发布包、内部分发包、`aifanyi` 发布工作区
- `localization-workflow-studio-data`

如果用户任务属于工作台，直接回复：

```text
这属于工作台线程，不在本线程范围。请切换到 localization-workflow-studio 工作台线程处理。
```

## 2. 仓库边界

主仓库：

```text
D:\codex\glossary-extraction-workflow
```

远端：

```text
https://github.com/zhangzeyu99-web/glossary-extraction-workflow
```

当前结构基线：

- branch: `main`
- upstream: `origin/main`
- 当前维护版本：`v0.4.0`
- 当前功能已拆分为 `glossary_extraction/` 包，`scripts/extract_glossary.py` 只作为 CLI 入口
- `D:\codex\localization-workflow-studio` 只消费本仓库的同步副本，不是本线程的主维护仓库

工作台同步规则：

- 本仓库是术语提取 workflow 的单一维护源。
- 工作台仓库内的 `workflow/glossary` 是只读同步副本。
- 不要直接改工作台内嵌副本。
- 如用户明确要求同步到工作台，应切换到工作台线程，由工作台线程在 `D:\codex\localization-workflow-studio` 根目录执行：

```powershell
python scripts/sync_workflow_sources.py glossary
```

## 3. 用户常见派任务方式

用户通常直接给本地目录或 Excel 文件，例如：

- `跑术语提取：C:\...\项目目录`
- `从这几份语言表补充术语表`
- `提取公告所需术语`
- `把这份术语表分类优化`
- `生成项目 brief`
- `根据语言表和注意事项更新 brief`
- `只保留中文术语`
- `补 EN/印尼/西葡译文`
- `分类只保留一个词，顺序不要变`
- `commit push / 更新 README / 做版本管理`

默认不要反问太多。先扫描真实目录和文件结构，判断输入类型，再执行。只有以下情况才问：

- 文件缺失
- 多个候选输入无法判断主源
- 会覆盖原文件且没有安全副本
- 用户要求互相冲突

## 4. 默认执行原则

1. 先读真实文件和目录，不凭记忆猜。
2. Excel 用 `openpyxl` 本地处理。
3. 大语言表必须本地脚本解析，不把完整语言表塞进模型上下文。
4. 模型只看统计、样本、候选摘要或 AI supplement packet。
5. 输出默认放回原目录。
6. 默认只交付最终 Excel 或 Markdown，不交付过程文件。
7. 交付前必须读回校验。
8. 最终回复只写交付路径、处理数量、校验结果和必要风险。

## 5. 术语提取工作流

输入可能包括：

- 完整语言表
- 已有术语表
- 翻译注意事项
- 公告文件
- 项目资料
- 已有项目 brief

默认流程：

1. 扫描目录，识别语言表、术语表、公告、注意事项、已有 brief。
2. 自动识别表头，常见列包括 `ID / CN / EN / EN2 / 分类`，或导出型 `索引ID / 内容 / 中文`。
3. 从语言表抽 CN 候选，按高价值术语筛选。
4. 用已有译文表验证译文。
5. 术语表译文和语言表实际译文冲突时，以语言表实际译文为准。
6. EN 默认只保留主译文；不要写 `A / B`。
7. EN2 只有用户明确要求双译法或历史工作流需要时才保留。
8. 分类默认放最后一列。

优先保留：

- 系统名、活动名、玩法名
- 装备、道具、资源、品质
- 技能、属性、战斗效果
- 纹章、铭文、宝石
- 副本、秘境、首领
- 英雄、职业、怪物、世界观专名

优先排除：

- 完整句子
- 临时提示句
- 普通动词泛词
- 数字礼包流水项
- 明显 UI 状态短句，除非用户明确要 UI 词

## 6. 分类规则

默认可用复合分类，例如：

- `活动/商城/奖励`
- `技能/战斗效果`
- `装备/道具`
- `纹章/铭文/宝石`
- `副本/秘境/首领`

如果用户要求“分类只保留一个词”，用单词分类：

- `活动`
- `UI`
- `操作`
- `装备`
- `道具`
- `资源`
- `品质`
- `属性`
- `技能`
- `纹章`
- `副本`
- `联盟`
- `英雄`
- `怪物`
- `宠物`
- `世界观`
- `邮件`

如果用户说“顺序不要变”，绝对不要排序，只改对应列。

如果用户说“补在最后面”，保留原表，新增术语追加到底部。

## 7. 译文处理规则

用户要求“译文填好”时：

- EN 必须非空
- 优先用已有语言表译文验证
- 没有证据的译文不要硬编

用户要求“英语只保留主译文”时：

- EN 只保留一个主译
- 清空 EN2
- 不保留 `A / B` 形式

用户要求“现有译文过长缩短”时：

- 把句子型 EN 改成术语型 EN
- `damage is increased` 可压缩为 `DMG Up`
- `Obtained from...` 可压缩为 `... Reward`
- 主译应短、可复用、适合术语表

## 8. 公告术语 lookup 工作流

用户给公告目录时：

1. 找公告文件：`docx / txt / md / xlsx`。
2. 找完整语言表，可以是一份或多份语言表。
3. 从语言表本地提取候选术语。
4. 只输出公告中实际出现的术语及译文。
5. 输出列与语言表交付格式保持一致，常见为 `ID / CN / EN` 或 `ID / CN / EN / FR...`。
6. 不把完整语言表交给模型。

AI 补充规则：

- AI 只看公告文本、已命中术语、少量本地摘取证据。
- AI 不能扫描完整语言包。
- AI 补充项必须满足：
  - 公告中出现
  - 有语言表译文证据
  - 置信度至少 medium
  - 有可追溯 ID 或句内证据
- 主 Excel 保持干净，不写置信度、证据、来源列。
- 验收报告默认不交付，只在最终回复说明命中数和风险。

## 9. 项目 brief 工作流

用户要求项目 brief 时：

1. 读取语言表、注意事项、术语表、已有翻译、项目资料、截图文字/OCR/文件名线索。
2. 输出 Markdown，通常命名为 `项目名-projectbrief.md`。
3. 内容只保留实用信息：
   - AI 生成的专属翻译提示词
   - 项目元信息
   - 翻译风格
   - 术语优先级
   - 代码/占位符/富文本规则
4. brief 要精简，不写长篇分析报告。
5. 必须总结常见代码用法。

常见代码用法：

- `{0}`、`{1}`
- `{0,Num}`、`{0,ItemName}`
- `#{style,text}`
- `[color=#xxxxxx]text[/color]`
- `[link]`
- `\n`
- `%d`

注意：不能把 `\n` 改成真实换行。

## 10. 交付表规则

常见术语表列：

```text
ID / CN / EN / EN2 / 分类
```

用户要求“干净交付表”时：

- 不加审计列
- 不加来源列
- 不加置信度列
- 不加解释列

用户要求“只保留中文”时：

- 输出 `ID / CN`，或保留原表但只填 CN，按上下文判断。

推荐命名：

```text
项目名-文件状态-日期.xlsx
```

示例：

```text
勇者术语表-已完成-20260706.xlsx
```

## 11. 校验要求

每次 Excel 交付前至少检查：

- 文件能用 `openpyxl` 打开
- sheet 存在
- 表头正确
- 总行数
- 空 CN 数
- 空 EN 数，如果任务要求译文
- 重复 CN 数
- 分类空值数
- 如果要求顺序不变，校验 ID/CN/EN 顺序完全不变
- 如果要求 EN2 清空，校验 EN2 非空为 0

最终回复示例：

```text
已完成，文件：xxx.xlsx。处理结果：原术语 757 条，新增 320 条，最终 1077 条；空 CN 0，空 EN 0，重复 CN 0，分类空值 0。顺序未变。
```

## 12. 固定验证命令

仓库测试：

```bash
python -m pytest -q
```

Harness 回归：

```bash
python scripts/run_glossary_harness.py fixtures/core_regression.json fixtures/observation_feedback_regression.json fixtures/announcement_lookup_regression.json fixtures/announcement_ai_supplement_regression.json
```

文档交付前：

```bash
python D:\codex\codex\tools\output_quality_gate.py README.md CHANGELOG.md docs\terminology-thread-handoff.md --expect-cjk
```

## 13. GitHub 与版本管理

只有用户明确说以下词时，才改仓库：

- `commit`
- `push`
- `更新 README`
- `版本管理`
- `发 GitHub`

仓库管理流程：

1. `git status --short --branch`
2. 确认只在 `D:\codex\glossary-extraction-workflow`
3. 跑测试和 harness
4. 文档改动跑输出门禁
5. commit 信息简短明确
6. push 后用 `git status --short --branch` 和 `git ls-remote` 校验
7. 如果打版本，更新：
   - `VERSION`
   - `CHANGELOG.md`
   - `README.md` 必要说明
   - git tag
   - GitHub Release，如用户要求完整版本管理

## 14. 新线程首条提示词

新线程可直接粘贴：

```text
你是术语提取执行线程，只负责 D:\codex\glossary-extraction-workflow，不负责 localization-workflow-studio 工作台更新。先阅读 docs/terminology-thread-handoff.md，再按里面的执行边界处理任务。用户通常会给本地目录或 Excel 文件，要求跑术语提取、公告术语 lookup、项目 brief、术语表分类和译文校验。执行时先扫描真实文件，用本地脚本/openpyxl 处理大表，不把完整语言包塞进模型上下文；交付前读回校验；最终只汇报交付路径、处理数量、校验结果和必要风险。
```

## 15. 沟通风格

用户希望执行型协作：

- 简体中文
- 结论先行
- 少废话
- 能做就做
- 不要一直问
- 不要输出大量过程
- 发现风险直接说
- 完成后只汇报关键改动、交付路径、验证结果
