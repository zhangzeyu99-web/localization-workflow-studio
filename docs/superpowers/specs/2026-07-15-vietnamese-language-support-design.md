# 越南语全工作台接入设计

## 目标

在工作台中新增越南语，并覆盖正式翻译、快速任务、公告、术语、QA、归档、导入导出和交付。

## 已确认口径

- Studio 内部 canonical code：`vn`。
- UI 标签与短码：`VN 越南语` / `VN`。
- 工作簿标准目标列：`VI`。
- Prompt 语言名：`Vietnamese`。
- 兼容请求代码：`vi`、`vie` 统一归一为 `vn`。
- 工作簿表头兼容：`VI`、`VIE`、`Vietnamese`、`越南语`、`越南文`。
- 不新增第二译文列。

`VN` 是本产品选定的内部代码；只读本地化引擎仍按既有规范把 `vn` 归一为 `vi`。工作簿继续使用 `VI`，避免修改 `workflow/localization` 或在运行时复制、改名、还原工作簿表头。

## 架构

### 语言注册

后端 `backend/app/languages.py` 是 Studio 的语言真源。新增 `vn` 规格，并把 UI 可见短码与目标表头分开：API 和队列状态返回 `visible_code/visible_language=VN`，工作簿与交付使用 `target_header=VI`。已有语言两者保持相同，不改变现有行为。

前端 `frontend/src/languages.ts` 注册 `vn`，以 API 返回结果刷新默认列表。`vi`、`vie` 在前后端都归一为 `vn`，防止旧调用或外部输入形成第二套语言数据。

### 底层执行

Studio 新增单一边界函数 `workflow_language_code()`：先把外部输入规范为 Studio canonical code，再仅在调用只读本地化子进程时将 `vn` 映射为 `vi`。正式翻译和 QA 的 subprocess 参数及 QA 输出文件名使用该底层代码；任务、API、数据库、归档和交付元数据继续保存 `vn`。这样能完整启用上游越南语文本规范与可读性检查，且无需修改同步产物。

### QA 写回

现有 QA 的机器检查已按运行语言取列，但人工修复、模型修复、逐句审校写回和自动变更记录仍有英语硬编码。把这些 helper 改成显式接收 `language`，统一使用 `target_aliases(language)` 定位目标列，确保 `vn` 及其他非英语语言完整可修复。

## 数据流

1. UI 选择 `vn`。
2. API、任务、归档、术语和交付元数据保存 `vn`。
3. 工作簿使用 `VI` 目标列。
4. Studio 在 subprocess 边界将 `vn` 映射为 `vi`，只读翻译工作流读写 `VI`。
5. QA、人工修复和模型修复依据 Studio 的 `vn` 规格定位 `VI`。
6. API/UI 始终回显 `VN 越南语`，不出现 `vi` 与 `vn` 两个语言选项。

## 验收标准

- `/api/languages` 只返回一个越南语项：`code=vn`、`visible_code=VN`、`target_header=VI`。
- 多语言队列状态返回 `language=vn`、`visible_language=VN`；工作簿和交付表头仍为 `VI`。
- `vn`、`vi`、`vie` 输入均保存为 `vn`。
- 新翻译任务、快速任务、公告任务和项目资产选择器显示且稳定保留 `VN 越南语`，不会启动后闪退。
- `VI` 工作簿能完成正式翻译、机器 QA、归档和交付。
- 越南语人工修复、模型修复和逐句审校能写回 `VI` 列，并生成变更记录。
- 宽表导入导出、术语和翻译归档包含越南语。
- 不修改 `workflow/localization` 和 `workflow/glossary`。
- 保留现有未提交改动；本任务不提交、不推送。
