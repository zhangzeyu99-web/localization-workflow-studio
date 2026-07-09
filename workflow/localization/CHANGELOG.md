# Changelog

## 2026-07-09 - 翻译 harness 语言支持扩充到历史需求全集

- `SUPPORTED_TRANSLATION_LANGUAGES` 从 6 语（en/ko/ja/th/vi/idn）扩充到 14 语，新增 fr/de/ru/it/es/pt/tr/ar。
- 依据：扫描历史交付记录（530 个 workbook 表头 + manifest/QA JSON）确认需求过的语言——土拨鼠 8 语深校（法/德/俄/意/西/葡/土/泰表头 33 文件）、明日2 全语种需求表（de/es/fr/pt/ru/tr 表头 20-30 文件）、勇者西葡全量、闪电突击 EN/IDN/ES/PT 四语、KR勇者公告、公告 harness 已有的 AR 列。
- `language_config.py` 六个注册表全部补齐 14 语（NAMES/ALIASES/FILE_HINTS/OUTPUT_SUFFIX/TARGET_HEADERS），中文别名（如"西班牙语""巴葡""阿语"）和常见代码变体（kr/jp/tk/pt-br）均可归一化。
- 新增 `tests/test_language_config.py` 注册表一致性守护：任何进 SUPPORTED 的语言必须六表齐全，防止半注册语言。
- `test_translation_harness.py` 新增 es/pt/ru/tr/ar 的 prepare+apply 端到端用例（含术语命中、目标列回填、缓存命名）和不支持语言拒绝用例。
- `run_translation_harness.py --lang` 帮助文案改为从注册表动态生成；AGENTS.md 语言清单指向 `language_config.py` 单一事实源。
- 回归：181 passed + 64 subtests（此前 174+25），ruff 0 error。

## 2026-07-09 - 移除旧版 Tkinter GUI

- 删除 `gui.py`（旧版人工复制粘贴流程入口，AGENTS 已长期声明不默认使用）；人工操作场景改用 `cli.py` 交互模式。
- 清理 README、`工作流说明.md`、`docs/使用说明书.md`、AGENTS.md 中的 GUI 入口引用；同步范围随之不再包含 `gui.py`。
- 如需找回历史实现，见 tag `pre-merge-20260709` 之前的 Git 历史。

## 2026-07-09 - Studio 演化合流与单一维护源确立

- 双向合并：吸收 studio 侧 `workflow/localization` 一个月的演化——large-text 多语言三件套（runner/gate/retro + 测试）、三个千行模块的职责拆分（announcement_docx_common/terms/prepare/apply、quality_harness_rules/terms、process_language_terms/review/outputs，原模块保留 re-export facade 和 `Boundary:` 标注）、AI review 辅助函数去重进 `utils/ai_checker.py`。
- 保留并接线本地未发布重构：`utils/language_config.py` 语言配置中心化（7 个模块统一导入）、`utils/term_rewrite_checker.py`、术语别名扩充（obtain/heal/dmg rate/dmg bonus/dmg reduction/spell def/crit res）、`text_normalize` 富文本宏保护、越南语/泰语支持并入拆分后结构（`TARGET_LANGUAGES` 新增 VI）。
- 确立本仓库为单一维护源：studio `workflow/localization` 降级为同步产物，经 `sync_workflow_sources.py` 镜像 + 哈希读回校验；同步门禁为 studio 的 workflow 测试与 backend 全量测试。
- 修复：`tests/test_workspace_runner.py` 文件名乱码（`鏈`→`术`）、`gui.py` 未用导入；新增与 studio 一致的 ruff 配置（`pyproject.toml`，select E9/F）。
- 回归基线：`python -m pytest -q` 174 passed + 25 subtests，ruff 0 error。

## 2026-05-18 - Project onboarding profile and prompt templates

- 项目定制 harness 流程新增前置阶段：项目开始时先收集游戏信息、游戏类型、目标市场、目标语言、核心玩法、术语、禁用译法、风格和技术约束。
- 新增 `templates/project_profile_template.md`，用于人工填写和评审单项目资料。
- 新增 `templates/project_profile_template.json`，用于脚本或项目 harness 读取结构化 profile。
- 新增 `templates/project_profile_template.yaml`，用于偏配置化项目的结构化 profile。
- 新增 `templates/translation_prompt_template.txt`，用于根据项目 profile 输出单项目翻译提示词，并通过 `--style-hint-file` 注入英语全量翻译 harness。
- 明确隔离规则：profile/prompt 只在单项目私有环境使用，不能跨项目复用；项目 harness 不强制 profile，但如果存在 profile 就必须读取并执行。

## 2026-05-18 - Project-custom harness workflow and delivery cleanup

- 新增 `docs/project-custom-harness.md`，把项目定制 harness 固定为通用 `quality_harness` 之后的项目级增强层，用于沉淀项目术语、风格、交付结构和历史错误拦截。
- 明确公开仓库边界：只提交通用流程、模板和文档；客户 workbook、参考样本、本地路径、项目专用术语和项目专用 harness 留在私有目录或 `.git/info/exclude` 隔离。
- 固定项目 harness 执行顺序：先通用最终门禁，再项目定制 QA；需要固定 workbook 结构时才启用 strict structure/reference 对比。
- 交付目录规则更新：最终版留任务根目录，`result_<lang>.xlsx` 和 `report_<lang>.xlsx` 放入 `qa_<lang>/`；`.translation_cache/` 作为过程缓存，最终交付前默认删除。

## 2026-05-15 - Color tag and punctuation boundary hardening

- Color tag QA 同时支持 `[color=#...]` 和 `<color=#...>`，翻译前后颜色代码必须一致，并且色值不会再被误判为内部代码。
- 术语命中增加变量边界处理，避免 `1小时` 误命中 `##1小时##2分钟` 这类 placeholder 数字结构。
- `word ? word` 分隔符污染规则收窄到源文含分隔符的场景，继续拦截 `Tank ? Basic Attack I`，但不误杀 `Press ? for help`。
- 英语 UI hard 预算继续按人工合格标准微调到 `min(32, max(10, source*2+14))`，允许清晰的短 UI 名词短语通过，避免为了预算压缩成坏缩写。

## 2026-05-15 - UI length hard budget relaxation

- 英语 UI hard 预算从 `min(26, max(8, source*2+8))` 放宽到 `min(30, max(10, source*2+12))`。
- 印尼语 UI hard 预算从 `min(28, max(9, source*2+9))` 放宽到 `min(32, max(11, source*2+13))`。
- 新增回归覆盖 `Showdown With Queen Bee` 这类 4 字中文 UI 的自然英文表达，避免为了过短预算继续压成不清楚的缩写。

## 2026-05-15 - Unified quality harness final gate

- `quality_harness --workbook` 现在接入 UI 长度检查，`ui_length_overflow` 为 hard gate，`short_text_length_watch` 作为软提示统计。
- workbook 术语扫描改为默认强约束：未显式标记 `soft/generic/common/参考/泛词/通用词` 的术语缺失、部分命中和大小写问题都会阻断交付。
- 连续编号词条一致性优先采用术语表标准；无术语时采用同批次首个通过基础可读性检查的译法，不再用多数派固化错误。
- 文档收口为 `AGENTS.md + quality_harness` 权威，README 和使用说明只保留摘要；英语全量翻译 harness 仍明确为 v1 仅支持英语。

## 2026-05-14 - Punctuation separator corruption gate

- `quality_harness` 将非问句中的 `word ? word` 分隔符污染纳入 `punctuation_corruption` hard gate，用于拦截 `Tank ? Basic Attack I` 这类非 ASCII 分隔符编码降级问题。
- 回归 fixture 同时保留正常疑问句好例，避免把 `Flying a Warplane? Let's try!` 这类自然英文误杀。

## 2026-05-14 - Numbered temporary term consistency gate

- `quality_harness` 新增 `numbered_term_inconsistency` hard gate：同一中文词根反复出现为 `词根-数字` 时，目标译文前缀、大小写和连字符格式必须一致。
- 该规则用于临时沉淀批内术语，拦截 `消灭怪物-#` 同时出现 `Kill Monsters-#`、`Destroy monsters-#`、`Kill monsters -#` 这类混译。
- 新增 workbook 级单元测试覆盖坏例和同表内好例，避免只靠人工截图发现批量编号任务名不一致。

## 2026-05-14 - Generic person-name term hard gate

- `quality_harness` 新增 `--term-base`，读取术语表中 `分类` 含 `人名` / `角色` / `person` / `character` / `name` 的条目。
- 最终 workbook 扫描命中中文人名时，目标译文必须使用术语表英文名，`Aria -> Arya`、`Leon -> Lyon` 这类近似名会作为 `person_name_term_mismatch` 阻断。
- `--workbook` 扫描现在会自动读取 workbook 内置术语表、同目录术语表，以及常见输出目录上一级的术语表；术语 QA 是默认闭环，不是交付前额外操作。
- 完整 workbook 作为 `--term-base` 时，只从真正术语表或显式 `分类/category/type` 表头的 sheet 收集人名术语，并跳过审计/裁决类辅助 sheet。
- 文档和 `AGENTS.md` 最终交付命令保持为 `--workbook <最终版.xlsx>`；`--term-base` 只作为自动发现失败或需要覆盖时的补充参数。

## 2026-05-14 - Generic workbook QA scan hardening

- `quality_harness` 的 workbook 扫描改为非只读读取，更接近交付前真实 Excel 状态。
- 真实 workbook 扫描现在会在 `rows_scanned=0` 时失败，避免空扫描被误判为 QA 通过。
- 通用扫描跳过 `术语表` / glossary sheet，避免把词典里的 Title Case 术语当正文错误误杀；正文和 UI 行仍必须真实扫描。
- 新增回归测试覆盖空扫描失败和 glossary sheet 跳过逻辑。

## 2026-05-12 - Project style hints for full translation

- 英语全量翻译 harness 新增 `--style-hint` 和 `--style-hint-file`，用于传入项目级短提示词，例如“面向美国移动端用户、SLG、简短地道表达”。
- `translation_manifest.json` 现在记录 `style_profile.project_hint`，`translation_workpack.jsonl` 每行也包含 `style_hint`，方便主 agent 翻译时按同一项目风格执行。
- `.translation_cache/en.jsonl` 增加提示词隔离：提示词不同的旧译文不会作为当前任务缓存命中，避免不同项目风格互相污染。
- 保持回填协议和 QA hard gate 不变：项目提示词只能优化表达风格，不能突破变量、标签、换行、术语和可读性门槛。

## 2026-05-12 - Full translation harness real-task validation

- 使用英语全量翻译 harness 重跑一份目标列为中文回填的真实语言表，完成 `prepare -> agent response -> apply -> --run-qa -> quality_harness` 闭环。
- 本轮验证覆盖 63 条语言表记录：`translation_response.jsonl` 按 ID 全量覆盖，回填阶段通过变量、标签、换行和 manifest 指纹校验。
- 最终机审结果为 `需人工确认: 0`，`quality_harness` 扫描真实 workbook 返回 `passed: True`。
- 剩余 `term_partial_hit: 3` 被确认为术语表机械匹配造成的软提示，不作为 hard gate 阻断；README 同步补充该判断口径。
- 交付目录策略验证通过：最终只保留 `_最终版.xlsx`、`output_en_final/result_en.xlsx`、`output_en_final/report_en.xlsx` 和隐藏 `.translation_cache`，临时 harness/probe 目录不作为交付物。

## 2026-05-12 - English full translation harness v1

- 新增 `scripts/run_translation_harness.py`，支持英语目标列为空、近乎全空或大面积中文回填时，先生成 `translation_workpack.jsonl`、`translation_manifest.json` 和 `translation_response.jsonl`。
- 新增 `utils/translation_harness.py`，负责列识别后的行级打包、文本类型分类、术语命中、占位符/标签/换行结构提取、response 协议校验、按 ID 回填和同项目隐藏缓存。
- 回填阶段会拒绝漏 ID、重复 ID、额外 ID、乱序、输入漂移、空译文、占位符漂移、标签漂移和换行漂移，避免全量翻译时串行或漏行。
- 新增 `.translation_cache/<lang>.jsonl` 同项目缓存策略，只复用当前任务目录译文，避免跨项目污染和目录杂乱。
- 新增 `docs/translation-harness.md` 和单元测试，明确该 harness 不调用 API，也不启用 subagent，由主 agent 直接生成译文后再由脚本校验回填。

## 2026-05-11 - Over-compression residue gate expansion

- 修复 `ID/CN/EN` 三列表头识别，避免把 `CN` 误当目标语言列导致全表中文残留误报。
- 扩展 hard gate，拦截 `TPRM#P` 这类内部代码加 `#` 的泄漏、`?R5` 这类项目符号损坏，以及 `Fina ATK SPD` 这类新截断残留。
- 补充消息/邮件场景截断规则，覆盖 `Repl This mess expi`、`No unre mess`、`Hara swip spam mess` 等四字母片段。
- 扩展四字符截断扫描，覆盖容量、钻石、奖励、修改、伤害、离线等场景的 `Capa`、`Diam`、`Rwds`、`Modi`、`Dama`、`Offl` 等片段。
- 扩展 `clipped_word` / `romanized_name_residue` 规则，覆盖 `Chef Yifang`、`Ener Scie`、`Stru Expe`、`Pts impr esse`、`No sear resu`、`Shen Armo`、`Orde Thun` 等新发现坏例。
- AI 审核 prompt 增加职业名、资源名、装备名、搜索结果文案不得截断缩写的约束。
- 新增回归样例，确保 `Divine Edge Armor`、`Thunder Order`、`No beds available` 这类自然译法不会被误杀。
- 重跑一组真实语言表和 UI 表：语言表修复 175 处典型过度压缩/拼音残留，UI 表无同类命中。
- 补充技能名/商店名/提示文案重灾区规则，覆盖 `Fast Trac Bull`、`Pene bull`、`Mult sanc`、`Inte guid`、`Glor Cont`、`Dese Cara`、`Cont cann empt`、`Your cont ##1`、`Loca cann plac`、`Wear equi cann rese`、`No wear equi`、`Stro equi Pack` 等整段截断。

## 2026-05-11 - UI length budget relaxation

- 放宽 UI hard 长度预算，英语从 `min(20, max(6, source*2+4))` 调整为 `min(26, max(8, source*2+8))`。
- 印尼语同步放宽到 `min(28, max(9, source*2+9))`。
- AI 审核 prompt 明确：hard 预算是显示保护线，不是机械压缩目标，不能为了进预算产生拼音、截断词或代码式缩写。
- 新增回归测试：`Divine Edge Armor`、`10 Improvement Essence` 这类自然短词不应被迫继续压缩。

## 2026-05-09 - Quality Harness

本次更新把会话中反复暴露的本地化质量问题沉淀成可执行 harness，目标是防止“越跑越差”。

### GitHub 项目管理

- 建立里程碑 `Quality Harness v1`
- 建立标签：`type:harness`、`type:workflow`、`type:docs`、`priority:p0`、`priority:p1`、`status:ready`、`status:backlog`
- 建立 issues `#2` 到 `#7`，覆盖最终交付 gate、CI、私有回归快照、delta report、多语言扩展和备份发布流程
- 新增 `docs/project-management.md`

### 新增

- 新增 `utils/quality_harness.py`
  - 统一运行变量/BBCode、中文残留、可读性、HTML 实体、内部 token、首字母小写、标点破坏、全角符号等检查
  - 增加 `hash_code_abbreviation`、`placeholder_compaction`、`placeholder_word_glue`，拦截 `#BRUL`、`S##1##2`、`##1Employed##2` 这类缩写残留
  - 支持固定字符串 fixture 和真实 workbook 扫描
- 新增 `scripts/run_quality_harness.py`
  - 可运行 `fixtures/quality_regression.json`
  - 可通过 `--workbook` 扫描最终版 Excel
  - 支持 `--json` 输出
- 新增 `fixtures/quality_regression.json`
  - 覆盖 `[v0]` 损坏、`ZXN37Q`、`Rare&#39;s`、`PERR`、`Logi time`、`Too Many Roles`、孤立 `’s`、句首小写、全角符号、问号变引号等回归用例
  - 同时保留 `7-Day Login`、`Battle Pass`、`HP`、占位符开头句子等好例，避免误杀
- 新增 `docs/quality-harness.md`

### 验证

- `python scripts\run_quality_harness.py fixtures\quality_regression.json`
- `python scripts\run_quality_harness.py fixtures\quality_regression.json --workbook <final-ui.xlsx> --workbook <final-language.xlsx>`
- `python -m unittest discover -s tests -p "test_*.py"`

## 2026-05-09

### 补充：英文大小写风格

- 新增 `title_case_overuse` 检查，拦截错误、状态、提示类文案里的无理由 Title Case，例如 `Too Many Roles`、`System Error`。
- `Logi time` 这类 `Login` 截断/拼错已纳入 `clipped_word` 检查。
- AI 审核 prompt 新增约束：英文错误、状态、提示类文案默认用 sentence case；Title Case 只用于专名、功能名、标题、商店项和术语表明确要求的名称。

### 可读性硬门槛

本次更新把“UI 过度压缩导致不可读缩写”的问题固化为流程硬门槛，避免最终版再次出现 `PERR`、`DTT`、`IJA`、`CL##1##2` 这类不可上线文案。

### 新增

- 新增 `utils/readability_checker.py`
  - 检测不可读缩写：`opaque_abbreviation`
  - 检测截断词 / 机械压缩词：`clipped_word`
  - 默认允许稳定游戏缩写：`HP`、`ATK`、`DEF`、`DMG`、`DPS`、`PVP`、`PVE`、`VIP`、`FPS`、`SFX`、`UI`、`Lv`
- 主流程在 UI 长度检查后增加“可读缩写 / 截断词检查”
- AI 审核 prompt 明确禁止为了长度预算发明不可读缩写或截断单词
- 新增规则文档：`docs/readability-abbreviation-gate.md`

### 规则变更

- `opaque_abbreviation` 和 `clipped_word` 现在属于最终版阻断错误，交付前必须清到 0。
- `Rwd`、`Req`、`Acct`、`Tmrw`、`OC`、`Mod` 不再默认视为安全缩写，除非项目术语表明确允许。
- 长度和可读性冲突时，以自然可懂为准，宁可略长。

### 验证

- `python -m unittest tests.test_readability_checker tests.test_process_language tests.test_ai_review_protocol`

## 2026-04-15

本次版本把近期已经验证过的工作流增强正式合入主线，重点是把“机审 -> AI 审核 -> 严格回填 -> 复核输出”这条链路补成稳定的闭环。

### 新增

- 严格 AI 审核协议
  - `prepare / merge` 使用 manifest 和 fingerprint 绑定批次
  - 模型回填必须逐条输出 `ID | KEEP` 或 `ID | FIX | corrected translation`
  - 缺行、乱序、输入漂移都会被直接拒绝合并
- 工作区批处理入口
  - 支持按目录自动发现语言表和术语表
  - 适合直接处理项目目录
- 拼音残留检测与自动修复
  - 支持识别 `Hongshangu`、`Jushizhen`、`Meiguihu`、`Xigu...`、`Lanshidi` 等专名残留
  - 对已知地图名和地点名可执行标准映射回写
- 短文本长度预算检查
  - 中文原文可见长度 `<= 10` 先进入候选池
  - `mode=hard`：紧凑 UI / 按钮 / 标签，作为硬约束
  - `mode=soft`：普通短文本，作为软提示
  - `mode=exempt`：编号专名、复杂富文本等直接豁免
  - AI prompt 会注入 `LEN:mode=...,source=...,target=...,budget<=...` 元数据

### 改进

- 强化占位符、BBCode、全角半角和富文本安全修复
- 支持在报告中识别 `romanized_name_residue`、`ui_length_overflow`、`short_text_length_watch`
- 同步更新 `README.md`、`工作流说明.md` 和 `docs/使用说明书.md`

### 使用注意事项

- 首跑建议 `batch-size=80~100`
- `prepare` 和 `merge` 之间不要替换或重排输入文件
- 短文本长度检查不是“全部 10 字以内都硬压”，而是先入池再分层
- 如果项目需要保留音译专名，建议显式维护到术语表或白名单

### 验证

- `python -m unittest discover -s tests -p 'test_*.py'`
- `python -m py_compile process_language.py utils\\ai_checker.py utils\\term_checker.py utils\\ui_length_checker.py tests\\test_ai_review_protocol.py tests\\test_ui_length_checker.py tests\\test_process_language.py`

结果：

- 单元测试通过
- 编译检查通过
