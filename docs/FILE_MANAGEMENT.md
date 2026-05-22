# 文件与数据管理

本文定义公开仓、私有运行数据和临时产物的边界。目标是让 GitHub 仓库保持干净，可公开、可复现、可维护。

## 文件分层

| 层级 | 位置 | 是否进 GitHub | 说明 |
|---|---|---|---|
| 产品源码 | `backend/`, `frontend/`, `workflow/` | 是 | 可公开的应用代码和工作流核心 |
| 项目文档 | `README.md`, `docs/` | 是 | 配置、存储、质量门槛、GitHub 管理、Pages Demo |
| 安全样例 | `examples/`, workflow fixtures | 是 | 合成数据或脱敏样例 |
| GitHub 配置 | `.github/` | 是 | CI、Issue 模板、PR 模板、依赖更新配置 |
| 本地运行数据 | `D:\codex\localization-workflow-studio-data` | 否 | 真实 workbook、SQLite、日志、settings、产物 |
| 临时输出 | `output/`, `test-results/`, `playwright-report/` | 否 | 截图、临时 XML、测试报告、调试文件 |

## 公开仓允许提交

- 源码。
- 合成样例。
- 测试 fixture。
- 文档。
- GitHub Pages 静态 Demo。
- 不含密钥、不含真实客户数据的示例配置。

## 禁止提交

- 真实语言表、术语表、校对表、客户素材。
- `settings.local.json`、API key、provider token。
- SQLite、run 日志、workpack、manifest、JSONL、QA 报告原始文件。
- 生成的 `*_translated.xlsx`、`*_final.xlsx`、`*_output.xlsx`。
- 本地截图、Playwright report、临时 XML、调试输出。

## 本地目录约定

默认数据目录：

```text
D:\codex\localization-workflow-studio-data
```

推荐结构：

```text
localization-workflow-studio-data/
  settings.local.json
  studio.sqlite3
  projects/
    <project_id>/
      uploads/
      assets/
      profile/
      glossary/
      runs/
      delivery/
```

真实项目文件只放这里，不放仓库根目录。

## 交付文件管理

最终交付只面向 QA 通过的任务。命名规则：

```text
{项目名}_{语言}_{YYYYMMDDHHmm}_{任务类型}-{短ID}_final.xlsx
{项目名}_{语言}_{YYYYMMDDHHmm}_{任务类型}-{短ID}_changes.xlsx
```

任务类型：

- `A`：完整向导任务。
- `T`：翻译任务。
- `QA`：只校对任务。

中间文件继续保存在 run 历史里，但不进入用户验收目录，也不提交到 GitHub。

## 清理检查

提交前检查：

```powershell
git status --short
git diff --check
git ls-files | Select-String -Pattern "settings.local|sqlite|api_key|translated.xlsx|final.xlsx|output.xlsx"
```

如果发现真实项目文件被 Git 跟踪，应先从索引移除，再确认 `.gitignore` 覆盖：

```powershell
git rm --cached <path>
```

不要删除用户本地真实数据；只从 Git 索引移除。

## GitHub Pages 边界

`docs/index.html` 是公开可分享 Demo，只能使用静态样例数据。

禁止在 Pages 中写入：

- 真实 workbook 内容。
- 客户素材。
- API key。
- SQLite 数据。
- 真实 run 日志。
- 可下载的真实交付文件。

完整版本需要独立后端和私有存储，不能依赖 GitHub Pages 保存上传内容。
