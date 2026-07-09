# 同步说明（请勿直接修改本目录）

本目录是本地化工作流的**同步产物**，不是维护源。

- 维护源（single maintenance source）：`D:\project\localization-workflow-project`（远端 https://github.com/zhangzeyu99-web/localization-workflow ）
- 职责：语言表翻译/校对 harness、大文本多语言 runner/gate/retro、公告 DOCX 处理、本地 QA。
- 同步方向：只允许 源仓库 → 本目录。任何直接改本目录的行为都是错误，会在下次同步时被覆盖。

## 给 AI/Agent 的规则

1. 需要改本地化工作流逻辑时：到 `D:\project\localization-workflow-project` 修改，先跑源仓库 `python -m pytest -q` 全绿。
2. 源仓库提交后，在 studio 仓库根执行统一同步脚本：

```powershell
python scripts/sync_workflow_sources.py localization
```

3. 脚本会自动做镜像复制 + 逐文件哈希读回校验（失败即非零退出）。
4. **强制门禁**：本目录中的 `process_language.py`、`scripts/run_quality_harness.py`、`scripts/run_translation_harness.py` 是工作台 backend 的 subprocess 运行时依赖（见各文件 `Boundary:` 标注）。每次同步后必须跑：

```powershell
python -m pytest workflow/localization/tests -q   # 本目录测试
python -m pytest backend/tests -q                 # 产品契约门禁，必须全绿
```

5. 同步范围：源仓库的代码与测试（`cli.py`、`process_language.py`、`workspace_runner.py`、`scripts/`、`utils/`、`tests/`、`templates/`、`fixtures/`、`requirements.txt`）。不同步源仓库私有资产：`docs/`、`tools/`、`examples/`、根目录中文文档/PDF/样例 xlsx、`README.md`、`AGENTS.md`。`SYNC.md` 保留在 studio 侧。
6. backend 里的 `app/workflow/large_text.py` 是从本目录 `utils/large_text_multilingual_gate.py` port 的受控复制，规则以本目录为准；改 gate 规则后要检查 `backend/tests/test_large_text_productization.py` parity 测试。

## 当前同步基线

- 最近一次同步：见 studio CHANGELOG 与 git 历史中 `chore: sync workflow/localization` 提交。
