# 2026-05-27 工作台线程上下文交接记录

## 结论

当前主要改动已集中在 `D:\codex\localization-workflow-studio`，核心目标是把工作台从单 EN 语言包流程扩展为 EN/KR/JP 多语言项目资产 + 项目内公告/外文本工作流，并同步底层公告术语 AI supplement 能力。本轮未收口项已补齐自动化与真实文件验收；等待提交推送和远端 CI 复核。

## 2026-05-27 收束更新

已收束内容：

- 公告 STEP 4 AI supplement 前端烟测已补进 E2E：
  - 勾选“启用 AI 漏词补充包”；
  - 上传 AI 补充响应 JSON；
  - 点击“提取公告术语 + 生成 AI 补充包”；
  - 校验漏词 `星界裂隙 -> Astral Rift` 并入任务内术语表；
  - 校验“导出术语表 / 下载 AI 补充包 / 下载 AI 报告”入口可见；
  - 继续跑到 workpack、AI response 导入、QA 回填、最终 ZIP 交付。
- 修复两个收束时发现的真实问题：
  - 公告任务 hydrate 未带出 `announcement_ai_supplement_packet/report`，导致 UI 显示“待生成”但无法下载。
  - 公告术语表 `ID | CN | JP` 会把首列 `ID` 误判为印尼语 ID；现已保留首个 `ID` 为标识列，只有重复/后续语言列才可作为 IDN。
- 前端提取按钮改为显式把当前 `aiSupplement` 和 response artifact id 传入 action，避免 React 状态刷新时闭包取旧值。
- 真实文件模拟跑已完成，按项目分类只选了 `日本主宰`：
  - 源文档：`C:\Users\Administrator\Desktop\工作台测试\日本主宰\_work\announcement_docx\source_input\主宰5.22版更.docx`
  - 已提取术语表：`C:\Users\Administrator\Desktop\工作台测试\日本主宰\日本主宰-源语言表公告术语-AI补充-已提取-20260527.xlsx`
  - AI response：使用同目录历史 `ai_response_ja.jsonl` 的译文内容，按本次 prepare 生成的 segment id 重映射。
  - 结果：21 段、60 条术语、语言 `JP`，最终 ZIP 内容为 `JP/主宰5.22版更_JP.docx` + `QA摘要.xlsx`，未包含 manifest/workpack/prompt/jsonl 等过程文件。
- 本轮最新本地验证：
  - `python -m pytest -q`：50 passed。
  - `cd frontend; npm run build`：通过。
  - `cd frontend; npm run e2e`：8 passed。
  - Google/deep_translator 禁用扫描：`NO_MATCHES`。

剩余项：

- 功能和验收口径已收束；只剩产品视觉偏好可继续看截图/手点调整，不再作为功能阻塞项。

## 当前代码状态

工作区：`D:\codex\localization-workflow-studio`

本轮业务改动主要分布：

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

注意：当前分支已有 Draft PR；本轮收束改动应追加到同一 PR，避免另开分支造成上下文分裂。

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

本轮 AI supplement 新增后已做自动化回归，并已补充前端 E2E 覆盖“启用 AI supplement + 上传 response + 导出术语表/packet/report”路径。

## 未完成任务 / 未收口内容

### 必须收口

以下历史必须收口项已处理：

1. **公告 STEP 4 AI supplement UI 验收**
   - 创建公告任务；
   - 上传语言表；
   - STEP 4 勾选“启用 AI 漏词补充包”；
   - 上传 response JSON，确认漏词并入术语表；
   - 下载入口：术语表、packet、report；
   - 状态：已由 `frontend/e2e/studio-ui-flow.spec.ts` 覆盖。

2. **AI supplement e2e smoke**
   - 状态：已补。
   - 额外覆盖：AI 补充 artifact hydrate 到任务详情，确保 UI 不再显示“待生成”。

3. **提交前整理 git diff**
   - 状态：本轮收束改动只涉及 announcement hydrate、ID 表头识别、STEP 4 e2e 和交接文档。

4. **最终真实文件模拟跑**
   - 建议用 `C:\Users\Administrator\Desktop\工作台测试` 下按项目分类挑 1 个 DOCX 或 TXT、1 个 XLSX，不要全量跑。
   - 状态：已选 `日本主宰` 跑通 DOCX + 已提取 JP 术语表 + AI response 导入 + apply + deliver。
   - 交付 ZIP：只含 `JP/*.docx` 和 `QA摘要.xlsx`。

### 可后续优化

1. `/api/projects/{id}/announcement-terms` 目前已支持 AI supplement 参数，但前端主入口走项目内 announcement task；旧轻量入口不作为主 UI。
2. AI supplement 目前是“接口/包/response 回填”，没有直接调用 provider 生成 supplement response；是否接入 OpenAI/Claude 需要另开需求。
3. 公告 TXT/XLSX adapter 是工作台侧轻量实现，DOCX harness 来自底层 workflow；复杂格式保真仍需更多真实文件回归。
4. 项目内公告译文默认不混入语言包译文归档；若要沉淀公告历史，需要单独定义公告归档视图。
5. 多语言语言包仍是多选拆单语言 run，不是真正单 run 多语言输出。

## 下一步建议

推荐顺序：

1. 提交并推送本轮收束改动到现有 PR。
2. 等远端 CI 复核。
3. 若 CI 通过，PR 可从 Draft 改为 Ready；后续只保留产品视觉微调，不再作为功能阻塞项。

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
