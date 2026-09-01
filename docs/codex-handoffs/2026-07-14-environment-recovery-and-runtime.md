# 本地化工作台环境恢复与运行状态 Handoff

日期：2026-07-14

## 交接目标

本次完成恢复后的运行环境补齐、前后端启动和启动器修复。后续任务应以本文和实时仓库状态为准，不需要读取旧大线程。

## 当前基线

- 仓库：`D:\codex\localization-workflow-studio`
- 分支：`master`
- HEAD：`af3ab0b fix(workflow): close multilingual processing and delivery gaps`
- 远端：`origin/master` 与本地 HEAD 一致
- 产品版本：`1.3.1`
- 运行数据：`D:\codex\localization-workflow-studio-data`
- 工作区：仅 `scripts/start-workbench.ps1` 有未提交修改
- `workflow/localization` 和 `workflow/glossary` 均未修改，仍是只读同步产物

## 已完成

### 1. 恢复运行环境

- 已确认 Git、Python、Node.js 和 npm 安装文件仍在：
  - Git：`D:\Git\cmd\git.exe`，`2.47.1.windows.2`
  - Python：`C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe`，`3.14.3`
  - Node.js：`D:\nodejs\node.exe`，`v22.22.1`
  - npm：`D:\nodejs\npm.cmd`，`11.12.0`
- Windows 用户 PATH 已包含以上目录；当前旧 Codex 进程仍可能保留恢复前 PATH，新开终端或重启 Codex 后会读取正确配置。
- 已按以下三份 requirements 补装缺失的 Python 依赖：
  - `backend/requirements.txt`
  - `workflow/localization/requirements.txt`
  - `workflow/glossary/requirements.txt`
- 前端 `node_modules` 完整，无需重新安装。
- `settings.local.json`、SQLite 数据库、项目数据和 provider 配置均存在；本文不记录任何密钥或中转站地址。

### 2. 修复启动器

`scripts/start-workbench.ps1` 当前有两处未提交修复：

1. 后台 PowerShell 改用 `-EncodedCommand` 启动，避免 PATH 和数据目录中的引号在 `Start-Process` 参数传递时丢失。
2. 前端启动后的 API 代理检查改为最多等待 15 秒，避免 Vite 页面先就绪、代理稍后就绪时被误判为启动失败。

不要撤销这份修改。提交前先审查 diff，并按本文验证门禁复测。

## 当前运行状态

以下状态会随重启变化，接管后必须实时复核：

- 后端：`http://127.0.0.1:8000/`
- 本地前端：`http://127.0.0.1:5173/`
- 局域网前端：`http://10.3.32.153:5174/`
- `8000`、`5173`、`5174` 的 `/api/health` 均返回 HTTP 200
- 独立端口监视进程正在运行；关闭启动窗口不影响服务和监视
- 当前数据库连接、数据目录写入、上传目录写入和 provider 配置检查均正常

统一控制入口：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/lws-workbench-control.ps1 -Action status
powershell -ExecutionPolicy Bypass -File scripts/lws-workbench-control.ps1 -Action restart
powershell -ExecutionPolicy Bypass -File scripts/lws-workbench-control.ps1 -Action stop
```

## 已通过验证

- PowerShell 解析 `scripts/start-workbench.ps1`：通过
- `git diff --check`：通过
- `python -m pip check`：`No broken requirements found`
- `python -m compileall -q backend workflow scripts`：通过
- 后端关键流程测试：`29 passed`
  - `backend/tests/test_ai_input_audit.py`
  - `backend/tests/test_multilingual_delivery.py`
  - `backend/tests/test_multilingual_orchestration.py`
- `npm --prefix frontend run build`：通过
- `scripts/deployment_check.py`：版本、前端资产、健康检查、上传读写均通过
- 本地页面、局域网页面及两侧前端 API 代理：HTTP 200

测试中仅出现一条 FastAPI TestClient 关于 `httpx2` 的弃用警告，不影响当前功能。

## 尚未执行

- 本轮没有运行完整 `python -m pytest -q`。
- 本轮没有运行 Playwright 全量 E2E。
- 启动器修复尚未提交或推送。

如果下一步要提交启动器修复，至少先重跑启动器冷启动、后端完整测试和前端 E2E；不要只凭当前端口在线直接提交。

## 新任务接管步骤

1. 先读取本文，不读取旧大线程。
2. 实时检查 `git status`、HEAD、远端差异、三个端口和监视进程，不照抄本文中的临时 PID 或局域网 IP。
3. 审查 `scripts/start-workbench.ps1` 的唯一未提交 diff，确认没有其他用户改动。
4. 保持 `workflow/localization` 与 `workflow/glossary` 只读；规则改动必须回源仓库后走同步脚本。
5. 若用户要求收口提交，执行完整验证后只提交本次启动器修复，再推送 `master`。

## 新任务输入

> 接管 `D:\codex\localization-workflow-studio`。先读取 `docs/codex-handoffs/2026-07-14-environment-recovery-and-runtime.md`，再实时检查仓库、服务和未提交改动。不要读取旧大线程，不要改只读的 `workflow/*` 同步产物；未获明确要求前不要提交或推送。
