# 2026-05-27 工作台线程上下文交接记录

## 结论

当前主要改动已集中在 `D:\codex\localization-workflow-studio`，核心目标是把工作台从单 EN 语言包流程扩展为 EN/KR/JP 多语言项目资产 + 项目内公告/外文本工作流，并同步底层公告术语 AI supplement 能力。当前代码未提交，测试通过，但仍需要产品侧人工验收和最终收口提交。

## 当前代码状态

工作区：`D:\codex\localization-workflow-studio`

未提交改动主要分布：

- 后端：
  - `backend/app/db.py`
  - `backend/app/main.py`
  - `backend/app/schemas.py`
  - `backend/app/workflow.py`
  - `backend/app/languages.py`（新增）
  - `backend/tests/test_mock_e2e.py`
- 前端：
  - `frontend/src/main.tsx`
  - `frontend/src/styles.css`
  - `frontend/e2e/studio-ui-flow.spec.ts`
- 内置 workflow：
  - `workflow/glossary/scripts/extract_glossary.py`
  - `workflow/glossary/scripts/run_glossary_harness.py`
  - `workflow/glossary/fixtures/announcement_lookup_regression.json`
  - `workflow/glossary/fixtures/announcement_ai_supplement_regression.json`
  - `workflow/glossary/tests/test_extract_glossary_workflow.py`
  - `workflow/glossary/tests/test_glossary_harness.py`
  - `workflow/localization/utils/announcement_docx_harness.py`
  - `workflow/localization/scripts/run_announcement_docx_harness.py`
  - `workflow/localization/tests/test_announcement_docx_harness.py`
  - 以及多语言 QA / harness 相关文件

注意：`docs/superpowers/` 当前也处于未跟踪状态；是否纳入提交需要单独确认，不要混进业务功能提交。

## 已落地的主要功能改动

### 1. EN/KR/JP 多语言项目资产模型

- 项目本身不再是“当前语言项目”；语言属于任务、QA、导入、公告检索等具体动作。
- 用户可见语言代码统一为：`EN / KR / JP`。
- 内部 canonical 仍是：`en / ko / ja`。
- 输入兼容：`KO/KR -> ko`，`JA/JP -> ja`。
- 新增 `backend/app/languages.py` 作为语言规范层。
- 术语、译文归档底层仍按语言隔离，前端展示改为宽表聚合。
- EN 保留 `EN2`；KR/JP 默认不展示、不导入 `KR2/JP2`。

### 2. 术语表 / 译文归档宽表

- 新增宽表 API 方向：
  - `GET /api/projects/{id}/glossary/wide`
  - `GET /api/projects/{id}/translations/wide`
- 宽表展示按 CN 聚合：`ID | CN | EN | EN2 | KR | JP | 分类 | 备注`。
- 导入语言表时可自动识别多语言列。
- 同项目同中文术语下 EN/KR/JP 可以并存，不互相覆盖。

### 3. 公告翻译 / 外文本项目内工作流

产品模型已调整为项目内功能，不再是全局公告入口。

9 步线性轴：

1. 公告资料：上传 DOCX / TXT / XLSX 源文档并创建任务。
2. 约束来源：选择语言表 / 术语交付表，默认叠加项目 QA 归档。
3. 目标语言：展示小语言框，识别到的语言默认勾选，可手动取消或勾选。
4. 术语提取：从公告原文提取任务内临时术语表，可导出、上传已有表、编辑保存。
5. 译文反查：QA 归档优先，语言表补缺。
6. 翻译准备：生成中转表、manifest、prompt snapshot、workpack。
7. AI 翻译 / 导入：正式 provider 可翻译，否则上传 `ai_response_<LANG>.jsonl`。
8. 校对回填：QA hard blocker 清零后生成同格式成品。
9. 交付：生成最终 ZIP。

UX 已处理过的口径：

- STEP 1 只上传公告源文档并创建任务，不展示语言子流程。
- 语言子流程只在需要时展示，不占住操作台。
- 目标语言用小框，不用大卡片。
- 文案不写“兼容”；用户可见用 KR/JP，不用 KO/JA。
- 约束来源只保留两类：上传语言表/术语表、项目已有 QA 归档。

### 4. 公告术语 AI supplement 同步

来源仓库：`D:\codex\glossary-extraction-workflow`

同步 commit：`e371a78d139858e2f33aee55b7742def8264da22`

commit 主题：`feat: add AI supplement interface for announcement glossary`

已同步能力：

- 本地精确 lookup 仍是默认主流程。
- 可选 `--ai-supplement`：生成精简 AI supplement packet。
- packet 只包含公告文本、已命中术语、少量相关句内证据；不把完整语言表直接交给模型。
- 可上传结构化 AI response JSON。
- 只有满足条件的补充术语并入主表：
  - 术语出现在公告原文中；
  - 有语言表证据；
  - `confidence >= medium`；
  - `action == add_to_main`；
  - 有对应语言译文。
- 输出 sidecar report，包含置信度、证据、项目名译文缺失提醒。

工作台接入点：

- `AnnouncementTaskActionRequest` 增加：
  - `ai_supplement: bool`
  - `ai_supplement_response_artifact_id: str | None`
- `AnnouncementTermsRequest` 增加同名字段。
- `GlossaryExtractRequest` 增加同名字段。
- 新增 artifact kind：
  - `announcement_ai_supplement_packet`
  - `announcement_ai_supplement_report`
- 前端 STEP 4 增加：
  - “启用 AI 漏词补充包”勾选项；
  - 上传 AI 补充响应 JSON；
  - 下载 AI 补充包 / AI 报告。

### 5. 交付规范化

语言包交付：

- 继续双 Excel：
  - `{项目名}_{LANG}_{YYYYMMDDHHmm}_{任务码}-{run短ID}_final.xlsx`
  - `{项目名}_{LANG}_{YYYYMMDDHHmm}_{任务码}-{run短ID}_changes.xlsx`
- `LANG` 使用 `EN/KR/JP`。
- `_changes.xlsx` sheet 固定为 `QA Changes`。
- `QA Changes` 表头固定：`工作表 | 行号 | 问题ID | 修改前 | 修改后 | 规则来源 | 备注`。

公告交付：

- 最终 ZIP：`{项目名}_{源文件名}_announcement_delivery_{YYYYMMDD}.zip`
- ZIP 只包含成品和 QA：
  - `EN/{源文件名}_EN.{ext}`
  - `KR/{源文件名}_KR.{ext}`
  - `JP/{源文件名}_JP.{ext}`
  - `QA摘要.xlsx`
- workpack、manifest、prompt、AI response、中转表不进入最终 ZIP，仅作为过程产物下载。

### 6. 禁止 Google / 外部机翻

已确认并保持：

- 工作流不得使用 Google Translate。
- 不使用 `deep_translator`、`googletrans`、浏览器翻译、在线机翻聚合器。
- 公告正文翻译只能走已配置 OpenAI / Claude provider，或上传外部 AI response。
- mock 只用于测试项目或显式 allow_mock 场景。

## 已执行验证

最近一次验证结果：

```powershell
# workflow/glossary targeted
python -m pytest workflow/glossary/tests/test_extract_glossary_workflow.py workflow/glossary/tests/test_glossary_harness.py -q
# 结果：39 passed

# backend + workflow full pytest
python -m pytest -q
# 结果：49 passed

# frontend build，注意必须在 frontend 目录
cd D:\codex\localization-workflow-studio\frontend
npm run build
# 结果：通过

# frontend e2e
npm run e2e
# 结果：8 passed

# 禁止 Google / deep_translator 检查
cd D:\codex\localization-workflow-studio
rg -n -i "deep_translator|googletrans|GoogleTranslator|translate\.google|google translate|Google Translate|GOOGLE_TRANSLATE|google_trans" backend workflow frontend --glob "!frontend/node_modules/**"
# 结果：NO_MATCHES
```

注意：在 `D:\codex\localization-workflow-studio` 根目录直接跑 `npm run build` 会误命中上层/其他 Node 配置或失败；正确目录是 `D:\codex\localization-workflow-studio\frontend`。

## 已做过的模拟验收口径

此前已经做过一次语言包和公告交付模拟验收，关键口径：

- 语言包 QA 交付生成双 Excel。
- 公告 TXT / DOCX / XLSX 成品 ZIP 保持输入格式。
- ZIP 内只包含语言目录成品和 `QA摘要.xlsx`。
- ZIP 不包含 `manifest.json`、`jsonl`、`prompt`、`workpack` 等过程文件。
- KR/JP 在 UI、文件名、目录名、表头中使用一致。

本轮 AI supplement 新增后已做自动化回归，但还没有单独做“前端手点启用 AI supplement + 上传 response + 导出术语表”的人工 UI 验收。

## 未完成任务 / 未收口内容

### 必须收口

1. **人工 UI 验收公告 STEP 4 AI supplement**
   - 创建公告任务；
   - 上传语言表；
   - STEP 4 勾选“启用 AI 漏词补充包”；
   - 先不上传 response，确认可生成 packet/report；
   - 再上传 response JSON，确认漏词并入术语表；
   - 下载术语表、packet、report 检查文件内容。

2. **确认是否给 AI supplement 补 e2e smoke**
   - 目前有 backend regression；
   - 前端 e2e 覆盖公告工作流基础路径，但未覆盖新勾选项和 response JSON 上传。

3. **提交前整理 git diff**
   - 当前改动很大，建议按功能拆提交：
     1. language config + EN/KR/JP normalized storage/display；
     2. glossary/translations wide view；
     3. announcement task workflow；
     4. delivery normalization；
     5. glossary workflow AI supplement sync；
     6. frontend UX polish；
     7. tests/e2e。
   - 不建议把 `docs/superpowers/` 混进业务提交，除非确认它是必要文档。

4. **最终真实文件模拟跑**
   - 建议用 `C:\Users\Administrator\Desktop\工作台测试` 下按项目分类挑 1 个 DOCX 或 TXT、1 个 XLSX，不要全量跑。
   - 重点验收：术语提取、AI supplement packet、译文反查、prepare、外部 response 导入、apply、deliver。

### 可后续优化

1. `/api/projects/{id}/announcement-terms` 目前已支持 AI supplement 参数，但前端主入口走项目内 announcement task；旧轻量入口不作为主 UI。
2. AI supplement 目前是“接口/包/response 回填”，没有直接调用 provider 生成 supplement response；是否接入 OpenAI/Claude 需要另开需求。
3. 公告 TXT/XLSX adapter 是工作台侧轻量实现，DOCX harness 来自底层 workflow；复杂格式保真仍需更多真实文件回归。
4. 项目内公告译文默认不混入语言包译文归档；若要沉淀公告历史，需要单独定义公告归档视图。
5. 多语言语言包仍是多选拆单语言 run，不是真正单 run 多语言输出。

## 下一步建议

推荐顺序：

1. 先做人工 UI 验收 STEP 4 AI supplement。
2. 如果 UI 没问题，补一条 e2e smoke 覆盖“启用 AI supplement + response 上传”。
3. 跑完整验证：`python -m pytest -q`、`frontend npm run build`、`frontend npm run e2e`、Google 禁用 rg。
4. 整理 diff，决定是否拆提交。
5. 再做真实文件模拟跑和交付验收。

## 关键原则，后续不要改偏

- 用户可见语言代码：`EN / KR / JP`。
- 内部语言：`en / ko / ja`。
- KR/JP 不默认生成第二译文字段。
- 公告任务是项目内功能，不是全局入口。
- STEP 1 只创建公告任务，不提前展示语言子流程。
- 术语提取结果是任务内临时资产，不自动写回项目术语库。
- QA 归档优先于上传语言表。
- 缺失术语提示但不默认 hard blocker。
- hard blocker 未清零不允许最终交付。
- Google / deep_translator / googletrans 永远不进翻译链路。
