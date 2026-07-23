# 稳定性验收清单

目标：确认工作台脱离 Codex/Agent 后，仍能只靠本地后端、内置 workflow 和已配置 API provider 完成核心流程。

## 生产 profile 与发布包

发布前只构建一次前端，再从 clean commit 生成所需制品。默认命令保留 universal 包；本次内网无账号交付使用 `--no-account`：

```powershell
npm run build --prefix frontend
python scripts/build_release_package.py --output-dir release_archives --no-rebuild-frontend
python scripts/build_release_package.py --output-dir release_archives --no-rebuild-frontend --no-account
```

默认输出名为 `localization-workflow-studio-v1.6.2-g<sha12>-universal.zip`；无账号输出名必须为 `无账号-v1.6.2.zip`，包内根目录为 `localization-workflow-studio-v1.6.2-g<sha12>-cloud-off`。每个 ZIP 旁边必须有同名 `.sha256`，包内必须包含 `PACKAGE_MANIFEST.json`、`SHA256SUMS.txt` 和 `DEPLOY_README.zh-CN.md`。

无账号 manifest 必须是 `artifact_kind=profile`、`default_runtime_profile=cloud-off`、`supported_runtime_profiles=["cloud-off"]`。包内 `start-lws.sh`、`deploy/lws.service` 和 `deploy/lws.env.example` 必须同时锁定 `cloud/off`；启用的环境模板和 `DEPLOY_README.zh-CN.md` 不得要求 `LWS_ADMIN_USER`、`LWS_ADMIN_PASSWORD`、`--auth-user` 或 `--auth-password`。

专用包的 manifest 只声明 Linux backend、backend app、deployment check 和 stability check 四个入口。包内不得携带 Windows `local/off` 启动器、`create_admin.py`、`local-off.env.example` 或 `cloud-required.env.example`，避免出现 manifest 只声明 `cloud-off`、制品却仍提供其它 profile 入口的旁路。

### 本地 `local/off`

Windows 解压包入口显式固定为 `local/off`：

```powershell
$Manifest = Get-Content -Raw PACKAGE_MANIFEST.json | ConvertFrom-Json
$DataRoot = Join-Path $env:LOCALAPPDATA 'LocalizationWorkflowStudio\data'
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-workbench.ps1 -HostName 127.0.0.1 -FrontendPort 5173 -DataRoot $DataRoot -NoOpen
python check.py --base-url http://127.0.0.1:5173 --expect-deployment-mode local --expect-auth-mode off --expect-runtime-profile local-off --expect-version $Manifest.version --expect-git-sha $Manifest.git_sha --check-frontend-assets frontend\dist\assets
python scripts\stability_check.py --base-url http://127.0.0.1:5173
python scripts\concurrency_smoke.py
```

`check.py` 必须确认匿名业务 API 可用；UI 不显示登录、注册、用户和成员管理，设置入口对 synthetic local admin 可见。`stability_check.py` 的 `--base-url` 必须与本次实际 `-FrontendPort` 一致。

`concurrency_smoke.py` 默认自建临时数据目录和独立 18800 端口，并实际重启该临时后端验证恢复。只有确认目标也是隔离实例时才使用 `--base-url`；该模式不接管进程，因此会跳过重启检查。

### 内网无账号 `cloud/off`

使用 `无账号-v1.6.2.zip` 内已锁定的 `deploy/lws.env.example` 安装服务器环境。部署检查不传登录凭据：

```bash
VERSION="$(.venv/bin/python -c 'import json; print(json.load(open("PACKAGE_MANIFEST.json", encoding="utf-8"))["version"])')"
GIT_SHA="$(.venv/bin/python -c 'import json; print(json.load(open("PACKAGE_MANIFEST.json", encoding="utf-8"))["git_sha"])')"
.venv/bin/python check.py --base-url https://ai-lwstudio.example.com \
  --expect-deployment-mode cloud --expect-auth-mode off --expect-runtime-profile cloud-off \
  --expect-version "$VERSION" --expect-git-sha "$GIT_SHA" --check-frontend-assets frontend/dist/assets \
  --require-provider
.venv/bin/python scripts/stability_check.py --base-url https://ai-lwstudio.example.com
```

该 profile 必须确认匿名业务 API 返回 200、`/api/auth/me` 为 `auth_enabled=false` synthetic admin、登录和注册返回 403、网页设置修改返回 403、设置入口隐藏，并且启动 AI 任务前仍要求操作人昵称。它没有账号隔离，只能部署在外层已经限制访问者的可信公司内网。

### 线上有账号 `cloud/required`

使用 `deploy/profiles/cloud-required.env.example` 安装服务器环境；`start-lws.sh` 默认 `cloud/required`。部署检查使用包内 Python 环境和 manifest 身份：

```bash
VERSION="$(.venv/bin/python -c 'import json; print(json.load(open("PACKAGE_MANIFEST.json", encoding="utf-8"))["version"])')"
GIT_SHA="$(.venv/bin/python -c 'import json; print(json.load(open("PACKAGE_MANIFEST.json", encoding="utf-8"))["git_sha"])')"
.venv/bin/python check.py --base-url https://ai-lwstudio.example.com \
  --expect-deployment-mode cloud --expect-auth-mode required --expect-runtime-profile cloud-required \
  --expect-version "$VERSION" --expect-git-sha "$GIT_SHA" --check-frontend-assets frontend/dist/assets \
  --require-provider --auth-user admin --auth-password '管理员密码'
.venv/bin/python scripts/stability_check.py --base-url https://ai-lwstudio.example.com --auth-user admin --auth-password '管理员密码'
```

该 profile 必须通过 HTTPS 验证 Secure `lws_session` cookie，并确认匿名业务 API 返回 401。

### Source E2E 与 extracted smoke

Task 6 的 source browser gates 使用以下真实命令：

```powershell
npm run e2e --prefix frontend
npm run e2e:auth --prefix frontend
```

各 extracted smoke 都必须运行 `frontend/e2e/runtime-profile-smoke.spec.ts`：按目标制品设置 `LWS_EXPECT_RUNTIME_PROFILE=local-off`、`cloud-off` 或 `cloud-required` 后，执行 `npx playwright test e2e/runtime-profile-smoke.spec.ts --config=playwright.config.ts --reporter=line`。universal 的 profile smoke 必须核对同一份 manifest 与 digest；专用无账号包的 `cloud-off` smoke 还必须核对 manifest 只声明 `cloud-off`。

双 lane 队列场景务必在隔离实例（临时数据目录、独立端口）上跑，不要对生产库跑。Linux 验收机可直接运行 `python3.11 scripts/concurrency_smoke.py --port 18800`。

## 必测项

1. `/api/version` 能返回当前版本和提交号。
2. `/api/health` 数据目录可写、上传目录可写、数据库可连。
3. 上传自检成功。
4. 创建项目。
5. 上传项目资料并完成 AI 分析。
6. 上传术语表、预览、导入、导出。
7. 上传语言表并完成 readiness 检查。
8. 正式翻译 run 能后台拆批、API 翻译、回填。
9. 直接 QA run 能完成并给出明确结果。
10. 译文归档能导入并导出 XLSX / CSV。
11. 快速任务能创建并跑到终态。
12. 公告任务能上传源文、识别约束、提取术语、反查译文、生成 prepare 产物。
13. 验收结束后临时项目被删除，线上不残留测试数据。
14. 大语言表/多语言包翻译 run 在 Step 7 显示 preflight 和 cache-lint 结果，交付时 readback gate 能阻断目标列缺失或空目标单元格的最终文件。

## 双 lane 持久队列测试项

15. 全局固定两条 lane：正式翻译、正式 QA/修复和多语言编排进入 `language_table`；快速任务全链路与公告翻译进入 `quick_announcement`。每条 lane 同时最多一个 `running`，两条 lane 可各运行一个任务。
16. 三个不同项目连续发起正式翻译时都返回成功：第一项 `running`，第二、三项按提交顺序 `queued`，完成或取消队首后依次推进；不再期待跨项目正式任务同时运行，也不再期待第三项返回 `capacity` 409（`scripts/concurrency_smoke.py` 覆盖）。
17. 快速任务与公告共享 `quick_announcement` lane 并严格 FIFO：先启动的快速任务运行时，后提交的公告显示为排队；不得出现该 lane 内两项同时 `running`（`scripts/concurrency_smoke.py` 覆盖）。
18. `GET /api/system/active-jobs` 只返回两条 lane 当前真正运行的任务；`GET /api/system/job-queues` 同时返回各 lane 的 running、queued、position 和 ahead，前端面板与项目状态必须一致。
19. 取消排队项后，该项立即变为 `canceled` 且永不执行，后续项仍保持原 FIFO 顺序；取消运行项时先持久化 `cancel_requested`，在阶段边界结束后自动调度下一项（`scripts/concurrency_smoke.py` 覆盖排队与运行取消）。
20. 后端重启时，原 `running` 队列记录转为 `interrupted`（已请求取消的转为 `canceled`），业务 run 恢复为可继续状态；原 `queued` 记录保留并在 handler 注册完成后自动继续，不能重复执行或永久卡住。默认自管模式的 `scripts/concurrency_smoke.py` 覆盖真实进程重启。
21. 一个任务运行期间，另一处修改全局 `settings.local.json`（provider/preset 等）不影响已经在跑的任务——任务在真正 dispatch 时读取一次 settings 快照，运行结果不受中途配置变更影响。
22. 项目存在 `staged/queued/running` 队列项时尝试删除该项目必须被拒绝；任务完成或取消后删除能正常成功，队列记录和业务数据一并清理。

## 账号与权限测试项（A1-A4）

23. 云端/强制登录部署下，未登录访问 `GET /api/projects`（或任意业务 API）返回 401；`check.py` 的 `anonymous_projects` 步骤覆盖这一项，`--require-cloud` 时是硬失败。
24. `member` 角色账号能跑正式翻译、快速任务和公告任务；正式翻译按既有规则写归档，快速任务与公告不回写归档。手动 `DELETE`/`PATCH` 术语、归档、项目资料，以及删除项目、管理项目成员，全部返回 403。
25. `member`/`ops` 账号访问自己不是成员的项目：列表中不出现该项目，直接按 id 访问返回 404（不是 403，防止项目存在性被枚举）。
26. 管理员停用一个用户后，该用户所有已签发 session 立即失效（下一次任意 `/api/*` 请求 401），不需要等 cookie 过期。
27. 首次登录（管理员引导账号或新建账号）在完成 `POST /api/auth/change-password` 之前，除 `GET /api/auth/me`、`POST /api/auth/logout`、`POST /api/auth/change-password` 外的所有 `/api/*` 请求返回 403 `首次登录请先修改密码`。
28. `operator_audit.log` 能看到 `login`（登录成功）、`logout` 事件，且操作者字段是真实登录用户名/显示名，不是 `X-Operator` 请求头里的昵称；登录失败不产生 `login` 记录（防止爆破刷日志）。

## 失败即阻断

- 页面能打开但 `/api/version` 404。
- `/api/version` 或 `/api/health` 的 deployment/auth/runtime profile 与本次期望不一致，或两个响应互相不一致。
- `cloud/off` 没有在启动阶段被拒绝。
- 两个 extracted smoke 不是同一个 artifact，或 manifest `version`/`git_sha`、frontend digest、runtime payload digest、outer ZIP SHA 任一不一致。
- 上传自检失败。
- 数据目录不可写。
- provider 未配置但尝试跑正式 AI 翻译。
- 下载最终交付文件返回 Not Found。
- 测试项目删除失败。
- 同一 lane 出现两个 `running`，或第三个正式任务仍因旧容量模型返回 409。
- 重启后 queued 任务丢失/重复执行，或 canceled 任务仍被 worker 执行。
- 云端/强制登录部署下，未登录访问业务 API 不是 401（fail-closed 失效）。
- 任一生产 profile 的 deployment check、stability flow、runtime Playwright 或临时项目/active jobs 清理失败。
- profile 切换导致项目、业务数据或文件丢失，或旧服务端/浏览器会话在切换后恢复有效。
