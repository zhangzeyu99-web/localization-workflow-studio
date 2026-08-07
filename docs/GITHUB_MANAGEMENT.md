# GitHub 管理

本文定义仓库维护、分支、CI、Issue、PR、版本和发布流程。

## 仓库入口

- Repository: <https://github.com/zhangzeyu99-web/localization-workflow-studio>
- GitHub Pages: <https://zhangzeyu99-web.github.io/localization-workflow-studio/>

## 分支策略

- `master`：唯一稳定发布分支。推送到该分支后应能通过 CI，并可作为 GitHub Pages 来源。
- `feature/<short-name>`：较大的功能改动。
- `fix/<short-name>`：明确缺陷修复。
- `docs/<short-name>`：文档、仓库治理、README、Pages 文案。

涉及运行行为、API、数据结构或 UI 主流程的改动，优先走功能分支或 PR；纯文档维护可直接提交到稳定分支。

## 提交范围

每次提交只覆盖一个清晰目标：

- 功能改动：源码 + 对应测试 + 文档说明。
- UI 改动：前端代码 + build/E2E 或浏览器验证。
- 工作流改动：`workflow/` 代码 + fixture/harness 测试。
- 文档改动：README/docs/.github，不夹带运行产物。

提交前确认没有真实项目数据、API key、SQLite、上传文件、交付文件、日志或缓存进入 Git：

```powershell
git status --short
git diff --check
git ls-files | Select-String -Pattern "settings.local|sqlite|api_key|translated.xlsx|final.xlsx|output.xlsx|uploads|runs"
```

## CI 与本地验证

GitHub Actions 覆盖：

- 后端与 workflow baseline tests、compileall、Ruff。
- 一次前端 TypeScript/Vite production build，并记录 canonical frontend tree digest。
- `local/off` 与 `local/required` 两套 source Playwright E2E。
- 由同一个 frontend dist 生成一个 universal ZIP，并在 Windows `local/off` 与 Ubuntu TLS `cloud/required` 中分别执行 extracted smoke。
- 两个 extracted smoke 读回同一 artifact ID、manifest `version`/`git_sha`、frontend digest、runtime payload digest 和 outer ZIP SHA。

当前 CI 不构建 `--no-account` 专用制品。`有账号-v1.7.2.zip` 与 `无账号-v1.7.2.zip` 必须在本地从同一 clean commit 生成；无账号包还必须把 archive readback、外部 SHA-256、Linux 脚本语法和 extracted HTTPS `cloud/off` smoke 作为独立发布证据，现有 universal publish gate 不能代替这组验收。

发布前本地建议执行：

```powershell
python -m pytest -q
python -m compileall -q backend scripts check.py
python -m ruff check backend scripts check.py

Push-Location frontend
npm run build
npm run e2e
npm run e2e:auth
Pop-Location

python scripts/build_release_package.py --output-dir release_archives --no-rebuild-frontend

rg -n -i "deep_translator|googletrans|GoogleTranslator|translate\.google|google translate|Google Translate|GOOGLE_TRANSLATE|google_trans" backend workflow frontend --glob "!frontend/node_modules/**"
```

## Issue 管理

Issue 应写清：

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

## PR 要求

PR 描述必须包含：

- 改了什么。
- 为什么改。
- 影响范围。
- 验证命令或页面操作。
- 是否影响数据目录、artifact、provider、QA 输出格式。

PR 模板位于 `.github/pull_request_template.md`。

## 版本管理

当前版本：`1.7.2`。稳定分支为 `master`；该版本发布说明见 [v1.7.2 公告文本与回填可靠性修复说明](releases/v1.7.2.md)。源码支持 `local/off`、`cloud/off` 与 `cloud/required`；有账号 universal 制品默认使用 `cloud/required`，独立无账号制品锁定为 `cloud/off`。

版本来源：

- `VERSION` 是产品版本的唯一真源；后端、包名、`PACKAGE_MANIFEST.json` 和生成的 `DEPLOY_README.zh-CN.md` 都从它派生。
- `frontend/package.json` 与 `frontend/package-lock.json` 的根包版本是同步镜像。
- `README.md`、`CHANGELOG.md`、`docs/index.html` 与 `docs/releases/vX.Y.Z.md` 必须同步当前公开入口。

规则：

- Patch：文档、UI 小修、兼容性修复、小范围 bug fix。
- Minor：新增用户可见流程、API、数据资产角色或 provider 能力。
- Major：破坏旧数据、旧 API 或旧 workflow 输入输出。

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
6. Release note 写清目标制品的验收结果、用户影响、数据/会话保证、部署状态和已知边界；没有线上验收证据时不得宣称已上线。
7. 仓库内无真实项目数据、API key、SQLite、run 日志或交付文件。
8. 文档无乱码、连续问号占位、U+FFFD 或历史版本误导。
9. universal 的两个 extracted smoke 必须核对同一 artifact 身份；专用无账号包必须另行核对 `artifact_kind=profile`、唯一 `cloud-off` profile、精简入口、外部 SHA、包内哈希和 extracted HTTPS 验收结果。

## GitHub Pages 管理

Pages 来源：

```text
branch: master
folder: /docs
```

`docs/index.html` 只作为静态 Demo/说明入口，不承载完整工作台功能。不要在 Pages 放真实上传文件、真实译文、API key、SQLite 或可下载交付文件。

## 依赖更新

Dependabot 配置位于 `.github/dependabot.yml`。

依赖更新原则：

- 依赖 PR 必须跑 CI。
- 前端依赖更新至少跑 `npm run build`。
- FastAPI、openpyxl、provider SDK 相关更新必须跑后端测试和 mock E2E。
- Playwright 更新必须跑浏览器 E2E。
