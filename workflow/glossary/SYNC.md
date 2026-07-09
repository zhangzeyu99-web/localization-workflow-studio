# 同步说明（请勿直接修改本目录）

本目录是术语提取工作流的**同步产物**，不是维护源。

- 维护源（single maintenance source）：`D:\codex\glossary-extraction-workflow`（远端 https://github.com/zhangzeyu99-web/glossary-extraction-workflow ）
- 职责：项目 brief 生成 + 术语提取/公告术语反查。
- 同步方向：只允许 源仓库 → 本目录。任何直接改本目录的行为都是错误，会在下次同步时被覆盖。

## 给 AI/Agent 的规则

1. 需要改术语提取逻辑时：到 `D:\codex\glossary-extraction-workflow` 修改，跑 `python -m pytest -q`（44+）和 harness fixtures 全绿。
2. 源仓库提交后，在 studio 仓库根执行统一同步脚本：

```powershell
python scripts/sync_workflow_sources.py glossary
```

3. 脚本会自动做镜像复制 + 逐文件哈希读回校验（失败即非零退出）。
4. 同步后在本目录跑读回测试：`python -m pytest workflow/glossary/tests -q`。
5. 同步范围：源仓库全部内容，除仓库管理文件（`.git/`、`.github/`、`.gitignore`）、缓存（`__pycache__/`、`.pytest_cache/`）、过程目录（`tmp/`、`output/`）和本文件（`SYNC.md` 保留在 studio 侧）。

## 当前同步基线

- 源版本：见本目录 `VERSION` 与 `CHANGELOG.md`（随同步带入）。
- 最近一次同步：2026-07-09（统一脚本接管，此前为 robocopy 手工命令）。
