# GitHub 管理

本文定义仓库维护、分支、CI、Issue、PR、版本和发布流程。

## 仓库入口

- Repository: https://github.com/zhangzeyu99-web/localization-workflow-studio
- GitHub Pages: https://zhangzeyu99-web.github.io/localization-workflow-studio/
- Feishu user guide: https://my.feishu.cn/docx/Pt9pdBypNoLy5MxYpZ3cr3A8nMc

## 分支策略

- `master`：稳定分支。推送到该分支后应能通过 CI。
- `feature/<short-name>`：较大的功能改动。
- `fix/<short-name>`：明确缺陷修复。
- `docs/<short-name>`：文档、仓库治理、README、Pages 文案。

小型文档维护可以直接提交到 `master`；涉及运行行为、API、数据结构或 UI 主流程的改动建议走分支和 PR。

## 提交范围

每次提交应只覆盖一个清晰目标：

- 功能改动：源码 + 对应测试 + 文档说明。
- UI 改动：前端代码 + E2E 或截图验证。
- 工作流改动：workflow 代码 + fixture / harness 测试。
- 文档改动：README / docs / `.github`，不夹带运行产物。

提交前必须确认没有真实项目数据进入 Git：

```powershell
git status --short
git diff --check
git ls-files | Select-String -Pattern "settings.local|sqlite|api_key|translated.xlsx|final.xlsx|output.xlsx"
```

## CI

GitHub Actions 跑：

- Backend mock E2E。
- Localization workflow baseline tests。
- Glossary workflow baseline tests。
- Frontend TypeScript / Vite build。
- Browser E2E against local FastAPI + Vite stack。

本地对应命令：

```powershell
python -m pytest -q

Push-Location workflow\localization
python -m pytest -q
Pop-Location

Push-Location workflow\glossary
python -m pytest -q
Pop-Location

Push-Location frontend
npm run build
Pop-Location
```

UI 或主流程变化还需要跑浏览器 E2E。

## Issue 管理

Issue 应写清楚：

- 当前行为。
- 期望行为。
- 复现步骤或任务入口。
- 影响的项目资产、run、artifact 或页面。
- 验收条件。

推荐标签：

- `type:bug`
- `type:enhancement`
- `type:docs`
- `area:frontend`
- `area:backend`
- `area:workflow`
- `area:qa`
- `area:storage`
- `priority:p0`
- `priority:p1`
- `priority:p2`

P0 表示阻断真实交付；P1 表示阻断验收或造成明显误导；P2 表示重要但不阻断。

标签清单维护在 `.github/labels.yml`。如果 GitHub 上的实际标签和该文件不一致，以该文件为准手动同步。

## PR 要求

PR 描述必须包含：

- 改了什么。
- 为什么改。
- 影响范围。
- 验证命令或页面操作。
- 是否影响数据目录、artifact、provider、QA 输出格式。

PR 模板位于 `.github/pull_request_template.md`。

## 版本管理

版本号同步维护：

- `VERSION`
- `backend/app/main.py`
- `frontend/package.json`
- `frontend/package-lock.json`

规则：

- Patch：文档、UI 小修、兼容性修复、小范围 bug fix。
- Minor：新增用户可见流程、API、数据资产角色或 provider 能力。
- Major：破坏旧数据、旧 API、旧 workflow 输入输出。

打 tag：

```powershell
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

## Release checklist

发布前确认：

1. README 入口、版本号、文档链接是最新的。
2. `docs/FILE_MANAGEMENT.md` 和 `.gitignore` 覆盖新增运行产物。
3. 本地核心测试通过，或明确说明未跑原因。
4. GitHub Actions 通过。
5. GitHub Pages Demo 可打开。
6. 飞书说明书如有流程变化已同步。
7. Release note 写清楚用户影响和迁移要求。

## GitHub Pages 管理

Pages 来源：

```text
branch: master
folder: /docs
```

`docs/index.html` 只能作为静态 Demo。不要在这里放真实上传文件、真实译文、API key、SQLite 或可下载交付文件。

## 依赖更新

Dependabot 配置位于 `.github/dependabot.yml`。

依赖更新原则：

- 依赖 PR 必须跑 CI。
- 前端依赖更新至少跑 `npm run build`。
- FastAPI / openpyxl / provider SDK 相关更新必须跑 backend tests 和 mock E2E。
- Playwright 更新必须跑浏览器 E2E。
