# 双项目整体检视与优化落地记录（2026-07-08）

对象：本地化工作流（`workflow/localization`，agent 侧）与术语提取项目（`D:\codex\glossary-extraction-workflow` 独立仓库 + `workflow/glossary` 内嵌副本）。

## 检视发现的问题（先问题后成果）

1. 术语提取双份维护漂移：独立仓库有 v0.3.0 / CHANGELOG / VERSION，内嵌副本却单独打了 UTF-8 stdio 修补和更高的依赖下限，两边各有对方没有的改动，没有明确的单一维护源。
2. 规则失效引用：`D:\codex\AGENTS.md` 引用的 `D:\codex\scripts\localization_pack_runner.py / gate.py / retro.py` 和 `docs/large_text_multilingual_workflow.md` 等路径在磁盘上已不存在，实际入口在 `workflow/localization/scripts/run_large_text_multilingual_*.py` 和 studio `docs/` 下。
3. 超大单体模块：`extract_glossary.py` 约 3,900 行（CLI、Excel IO、启发式、公告、AI provider、报告混在一起，公告 / AI supplement 流程在三个 CLI 分支重复三份）；本地化侧 `announcement_docx_harness.py` 1,180 行、`quality_harness.py` 1,027 行、`process_language.py` 985 行。
4. 边界不清与卫生问题：`workflow/localization` 下产品 subprocess 依赖入口和 agent-only 入口混放且无标注（`CONTEXT.md` 的双角色描述也与 backend 实际调用不完全一致）；`cli.py` 与 `workspace_runner.py` 重复维护 `_reset_review_dir` / `_collect_recheck_rows`；独立仓库工作树里有 `.pytest_cache/`。

## 决策

- 术语提取以独立仓库 `glossary-extraction-workflow` 为单一维护源；`workflow/glossary` 降级为同步产物（新增 `SYNC.md` 写明同步命令与禁改规则）。
- 优化做到深度层：安全层修复 + 大模块拆分，全部以"行为零变化 + 测试全绿"为验收线。

## 落地改动

### 术语提取（独立仓库，v0.3.0 → v0.4.0）

- 回灌内嵌副本独有的 `configure_utf8_stdio()` UTF-8 修补和测试编码修补；`requirements.txt` 抬到 `openpyxl>=3.1.5`、`pytest>=8.4.2`。
- `scripts/extract_glossary.py` 拆为 `glossary_extraction/` 包：`constants` / `models` / `heuristics` / `experience` / `excel_io` / `announcement` / `ai_supplement` / `reporting` / `cli` 九个模块；原脚本保留为 73 行门面，全量 re-export 原顶层符号并支持测试 monkeypatch 透传。
- 三个 CLI 分支重复的公告 / AI supplement 编排收敛为 `cli.py` 中的共享函数（`run_announcement_glossary_outputs` 等）。
- 以独立仓库为源镜像同步 `workflow/glossary` 并做哈希读回校验（0 差异），内嵌副本测试独立复跑通过。

### 本地化工作流（studio，1.0.3 → 1.0.4）

- 三个千行模块拆分（纯搬移 + import 重组，原模块保留为兼容门面，公开符号不变）：
  - `utils/quality_harness.py` → `quality_harness_rules.py`(449) + `quality_harness_terms.py`(307)，门面 215 行；
  - `utils/announcement_docx_harness.py` → `announcement_docx_common.py`(143) + `announcement_docx_terms.py`(261) + `announcement_docx_prepare.py`(325) + `announcement_docx_apply.py`(384)，门面 88 行；
  - `process_language.py` → `utils/process_language_terms.py`(180) + `process_language_review.py`(266) + `process_language_outputs.py`(316)，本体 144 行（CLI + 编排 + re-export）。
- `cli.py` / `workspace_runner.py` 重复的 `_reset_review_dir` / `_collect_recheck_rows` 抽到 `utils/ai_checker.py`（`reset_review_dir` / `collect_recheck_rows`）。
- 全部入口加 `Boundary:` docstring 标注：产品 runtime 依赖为 `process_language.py`、`scripts/run_quality_harness.py`（backend `qa.py` subprocess）、`scripts/run_translation_harness.py`（backend `translation.py` subprocess）；agent-only 为 large-text 三件套、`run_announcement_docx_harness.py`、`cli.py`、`workspace_runner.py`。`CONTEXT.md` 按 backend 实际调用修正。

### 规则与卫生

- `D:\codex\AGENTS.md`：4 处失效路径改为真实存在的绝对路径（large-text runner/gate/retro 入口、大文本工作流文档、深度逐句校对文档、术语校对标准文档）。
- 清理独立仓库 `.pytest_cache/` 与两侧 `__pycache__`。

## 验收证据（最终树复跑）

| 检查 | 结果 |
|---|---|
| 术语独立仓库 `python -m pytest -q` | 44 passed |
| 术语 harness 全部 4 个 fixtures | all_passed: true，exit 0 |
| 内嵌副本读回 `python -m pytest tests -q` | 44 passed |
| 源与内嵌哈希比对（除仓库管理文件） | 0 差异 |
| `workflow/localization` `python -m pytest tests -q` | 154 passed + 14 subtests |
| `backend/tests` 全量（含 large-text parity） | 见 CHANGELOG 记录的收口结果 |

## 遗留与下一步

- `utils/announcement_docx_harness.py` 与 backend `announcement_outputs.py` 属平行实现（backend 未复用 workflow 版），后续如公告规则再演化，考虑像 large-text 一样补 parity 测试。
- 独立仓库尚无 CI（`.github/` 只有 issue template）；账号具备 workflow 权限后应补 GitHub Actions 跑 pytest + harness。
- `glossary_extraction/excel_io.py`（725 行）、`ai_supplement.py`（697 行）、`cli.py`（695 行）仍偏大，可在下次功能迭代时二次收敛，本次不为拆而拆。
