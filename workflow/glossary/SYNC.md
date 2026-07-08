# 同步说明（请勿直接修改本目录）

本目录是 `D:\codex\glossary-extraction-workflow`（独立仓库，单一维护源）的同步产物。

## 规则

- 所有代码、文档、fixtures 修改必须先落在独立仓库，跑通 `python -m pytest` 后再同步到这里。
- 禁止直接修改本目录内容；如在此处发现问题，回到独立仓库修复后重新同步。
- 同步范围不含独立仓库的 `.git/`、`.github/`、`.gitignore`、`.pytest_cache/`、`__pycache__/`、`tmp/`、`output/`。

## 同步命令

```powershell
robocopy D:\codex\glossary-extraction-workflow D:\codex\localization-workflow-studio\workflow\glossary /MIR /XD .git .github .pytest_cache __pycache__ tmp output /XF .gitignore SYNC.md
```

同步后在本目录运行 `python -m pytest tests -q` 做读回验证。

## 当前同步基线

- 源版本：见本目录 `VERSION` 与 `CHANGELOG.md`（随同步带入）。
- 最近一次同步：2026-07-08。

