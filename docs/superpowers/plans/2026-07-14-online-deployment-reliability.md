# Localization Workflow Studio Online Deployment Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不重做现有前端和业务流程的前提下，交付一个可稳定线上部署的本地化工作台，使上传、后台任务、页面刷新恢复、翻译缓存、产出列表和下载在部署及重启后保持可用。

**Architecture:** 第一阶段采用“单 Linux 实例 + 同源 HTTPS + 单 FastAPI worker + 持久 `LWS_DATA_ROOT`”作为唯一验收基线。Nginx 负责静态前端和 `/api/` 反向代理；FastAPI 只读写同一个持久数据目录，其中包含 `settings.local.json`、SQLite、上传、任务、翻译缓存和产出。Sites 不能单独承载当前 Python/SQLite/本地文件后端；若仍需使用 Sites，只在该基线通过后把前端发布到 Sites，并通过同源 Worker 代理或完整 API URL 解析连接外部 FastAPI。

**Tech Stack:** React 19、Vite 7、TypeScript、FastAPI、SQLite WAL、Nginx、systemd、Python 3.11、现有 Playwright/pytest/部署自检脚本。

## Global Constraints

- 保留 `frontend/` 现有页面、组件和业务流程；不做视觉重设计。
- 不直接修改只读同步产物 `workflow/localization` 和 `workflow/glossary`。
- 不覆盖当前未提交的 `scripts/start-workbench.ps1` 和 `docs/codex-handoffs/2026-07-14-environment-recovery-and-runtime.md`。
- `settings.local.json`、API key、SQLite、上传和产出不得进入 Git、公开前端或公开发布包。
- 线上只运行一个 FastAPI 实例、一个 uvicorn worker；第一阶段不做横向扩容。
- `LWS_DATA_ROOT` 必须位于发布目录之外的持久卷；代码升级、服务重启和版本回滚不得更换该路径。
- HTML/API 不缓存；带内容哈希的 `/assets/*` 长期缓存；翻译缓存随项目数据持久化。
- 所有部署验收从用户访问的 HTTPS 地址执行，不能只测 `127.0.0.1` 后端。
- 未取得实际故障站点 URL 或 HAR 时，根因保持为“按代码证据排序的假设”，不能写成已确认线上根因。

---

## Current Workspace Overview

### Confirmed facts

- 当前仓库为 `master` / `af3ab0b` / `1.3.1`，与 `origin/master` 对齐。
- 当前工作区有两项用户改动：`scripts/start-workbench.ps1` 已修改；`docs/codex-handoffs/2026-07-14-environment-recovery-and-runtime.md` 未跟踪。
- 本地 `8000`、`5173`、`5174` 的 `/api/health` 均为 HTTP 200；`/api/version` 返回当前版本、提交号和数据目录。
- 当前数据模型已经完整：`$LWS_DATA_ROOT/settings.local.json`、`studio.sqlite3`、`projects/`、`runs/`、上传、交付和 `.translation_cache/`。
- `frontend/src/apiClient.ts` 已支持 `VITE_API_BASE_URL`；但后端产出 URL 和多个下载链接仍是 `/api/...` 相对路径，前后端跨域部署时会落到错误的前端域名。
- Vite 的 `/api` 代理只在开发服务器生效；静态 `frontend/dist` 自身不会代理 API。
- 前端项目、视图、Tab 和步骤只保存在 React 内存中；整页刷新后会重新选择后端项目列表第一项并回到概览。
- FastAPI 已为 `/api/*` 增加 `Cache-Control: no-store`；现有 Nginx 文档也区分了不缓存 HTML/API 与长期缓存哈希资源。
- 仓库记录的 GitHub Pages 地址当前返回 404，且 `/api/version` 也返回 404；它不能作为可用工作台基线。

### Ranked hypotheses to verify against the broken deployment

1. **API 未与静态前端组成同源部署。** 预测：页面可以加载，但用户域名的 `/api/version` 返回 404、HTML 或代理错误，上传自然无法进入 FastAPI。
2. **`LWS_DATA_ROOT` 位于临时层或重启时发生变化。** 预测：SQLite 中仍有 artifact 记录但文件 `exists=false`，或重启后项目、上传和交付整体消失。
3. **前后端跨域时下载 URL 没有拼接 API origin。** 预测：项目/产出 API 能返回数据，但点击 `/api/projects/.../download` 时请求发往前端域名并 404。
4. **CDN/Nginx 缓存策略覆盖了应用的 `no-store`。** 预测：公开域名的 `/api/version`、项目列表或 `index.html` 出现旧版本、`Age`/缓存命中，刷新看到不同状态。
5. **刷新恢复属于前端未持久化状态，而非后端数据丢失。** 预测：刷新后后端项目和 run 都存在，但前端回到第一个项目、概览 Tab 和第一步。

---

### Task 1: Capture a deterministic failing online probe

**Files:**
- Modify: `scripts/deployment_check.py`
- Create: `backend/tests/test_deployment_contract.py`
- Test: `backend/tests/test_deployment_contract.py`

**Interfaces:**
- Consumes: public site base URL and existing `/api/version`, `/api/health`, `/api/diagnostics/upload-readability` endpoints.
- Produces: a single JSON result that distinguishes frontend, API proxy, storage, provider, cache headers and download routing failures.

- [ ] **Step 1: Add failing deployment-contract tests**

  Cover these exact assertions with FastAPI `TestClient` and a temporary `LWS_DATA_ROOT`:

  ```python
  def test_api_contract_is_no_store(client):
      for path in ("/api/version", "/api/health", "/api/projects"):
          response = client.get(path)
          assert response.status_code == 200
          assert response.headers["cache-control"] == "no-store"

  def test_artifact_download_round_trip(client):
      sample_upload = b"id,source,en\n1,Hello,\n"
      project = client.post("/api/projects", json={"name": "download-probe", "type": "qa"}).json()
      artifact = client.post(
          f"/api/projects/{project['id']}/files?kind=language_table",
          files={"file": ("probe.csv", sample_upload, "text/csv")},
      ).json()
      detail = client.get(f"/api/projects/{project['id']}").json()
      assert any(item["id"] == artifact["id"] and item["exists"] for item in detail["artifacts"])
      assert client.get(f"/api/projects/{project['id']}/artifacts/{artifact['id']}/download").content == sample_upload
  ```

- [ ] **Step 2: Run the new tests and confirm the public API contract is deterministic**

  Run: `python -m pytest backend/tests/test_deployment_contract.py -q`

  Expected: API cache headers and upload/download round-trip both pass. Process restart persistence is covered at the correct deployment seam in Task 5 instead of being simulated inside one Python process.

- [ ] **Step 3: Extend `scripts/deployment_check.py` with public-edge checks**

  Add checks for:

  ```python
  checks["frontend_content_type"] = response.headers.get("content-type", "")
  checks["api_content_type"] = version_response.headers.get("content-type", "")
  checks["api_cache_control"] = version_response.headers.get("cache-control", "")
  checks["api_is_json"] = "application/json" in checks["api_content_type"]
  checks["api_is_no_store"] = "no-store" in checks["api_cache_control"].lower()
  ```

  The command must fail when `/api/version` returns HTML, redirects to a login page without an authenticated session, lacks `no-store`, or reports a different version from the local `VERSION` file.

- [ ] **Step 4: Add a download round-trip probe**

  The probe creates a temporary project, uploads a small workbook, reads the returned artifact through project detail, downloads it through the public base URL, compares SHA-256, then deletes the temporary project in `finally`.

- [ ] **Step 5: Run the probe against local frontend origin**

  Run: `python scripts/deployment_check.py --base-url http://127.0.0.1:5173 --expect-version 1.3.1 --check-frontend-assets`

  Expected: `frontend/api/storage/upload/download/cache = passed`.

- [ ] **Step 6: Run the probe against the actual broken HTTPS URL**

  Run: `python scripts/deployment_check.py --base-url $env:LWS_PUBLIC_URL --require-cloud --require-provider --expect-version 1.3.1 --check-frontend-assets`

  Expected: FAIL at one named boundary, not a generic “site unusable” result.

- [ ] **Step 7: Commit the isolated diagnostic contract**

  ```bash
  git add scripts/deployment_check.py backend/tests/test_deployment_contract.py
  git commit -m "test: add public deployment contract probe"
  ```

### Task 2: Make deployment topology explicit and reproducible

**Files:**
- Create: `deploy/lws.service`
- Create: `deploy/nginx.conf.template`
- Create: `deploy/install.sh`
- Create: `deploy/lws.env.example`
- Modify: `start-lws.sh`
- Modify: `docs/CLOUD_DEPLOYMENT.md`
- Test: `scripts/deployment_check.py`

**Interfaces:**
- Consumes: a checked-out release directory, Python 3.11, Node 22, Nginx, and a persistent data directory.
- Produces: one HTTPS origin where `/` serves `frontend/dist` and `/api/` reaches exactly one FastAPI worker.

- [ ] **Step 1: Define the deployment filesystem contract**

  Use this exact layout:

  ```text
  /opt/lws/releases/$LWS_GIT_SHA/     immutable code and frontend/dist
  /opt/lws/current -> releases/...   active release symlink
  /var/lib/lws/                      persistent LWS_DATA_ROOT
    settings.local.json
    studio.sqlite3
    projects/
    runs/
    uploads/
  /etc/lws/lws.env                   non-secret runtime paths/mode
  ```

- [ ] **Step 2: Add a systemd unit with one worker**

  `deploy/lws.service` must run:

  ```ini
  [Service]
  WorkingDirectory=/opt/lws/current
  EnvironmentFile=/etc/lws/lws.env
  ExecStart=/opt/lws/current/.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8082 --workers 1
  Restart=on-failure
  RestartSec=3
  PrivateTmp=true
  NoNewPrivileges=true
  ```

- [ ] **Step 3: Add a same-origin Nginx template**

  Preserve the existing cache rules and add proxy buffering/timeouts explicitly:

  ```nginx
  location = /index.html {
      add_header Cache-Control "no-cache" always;
      try_files $uri =404;
  }
  location /assets/ {
      add_header Cache-Control "public, max-age=31536000, immutable" always;
      try_files $uri =404;
  }
  location /api/ {
      proxy_pass http://127.0.0.1:8082;
      proxy_http_version 1.1;
      proxy_request_buffering off;
      proxy_buffering off;
      proxy_read_timeout 600s;
      proxy_send_timeout 600s;
      add_header Cache-Control "no-store" always;
  }
  location / {
      add_header Cache-Control "no-cache" always;
      try_files $uri $uri/ /index.html;
  }
  ```

- [ ] **Step 4: Make installation idempotent**

  `deploy/install.sh` must install Python dependencies, run `npm ci && npm run build` in `frontend/`, create the persistent directory without deleting existing data, install the unit/template, and refuse to continue if `/var/lib/lws/settings.local.json` is missing.

- [ ] **Step 5: Keep provider configuration server-side**

  `deploy/lws.env.example` contains only:

  ```bash
  LWS_DEPLOYMENT_MODE=cloud
  LWS_DATA_ROOT=/var/lib/lws
  LWS_MAX_UPLOAD_MB=1024
  LWS_CORS_ORIGINS=https://lws.internal.example
  LWS_GIT_SHA=af3ab0b7941c
  ```

  The provider/base URL/API key/model remain only in `/var/lib/lws/settings.local.json`. The installer must not echo its content.

- [ ] **Step 6: Add fail-fast startup validation**

  Before starting uvicorn, `start-lws.sh` must verify the data directory is writable and `settings.local.json` parses as JSON. Do not validate by printing secret values.

- [ ] **Step 7: Validate a fresh isolated installation**

  Run the install in a disposable VM/container with an empty release directory and a mounted persistent `/var/lib/lws`, then run:

  ```bash
  python3.11 scripts/deployment_check.py --base-url "$LWS_PUBLIC_URL" --require-cloud --require-provider --expect-version "$(cat VERSION)" --check-frontend-assets
  ```

- [ ] **Step 8: Commit deployment templates and documentation**

  ```bash
  git add deploy start-lws.sh docs/CLOUD_DEPLOYMENT.md
  git commit -m "feat: add reproducible single-instance deployment"
  ```

### Task 3: Normalize API and download URLs for optional Sites hosting

**Files:**
- Modify: `frontend/src/apiClient.ts`
- Modify: `frontend/src/domain/artifacts.ts`
- Modify: `frontend/src/domain/projectApi.ts`
- Modify: `frontend/src/components/translationWizard/ProjectTabs.tsx`
- Modify: `frontend/src/components/translationWizard/TaskHistoryTable.tsx`
- Modify: `frontend/src/components/translationWizard/steps/StepDone.tsx`
- Modify: `frontend/src/components/translationWizard/steps/StepQA.tsx`
- Modify: `frontend/src/components/quickTask/QuickTaskWizard.tsx`
- Test: `frontend/e2e/studio-ui-flow.spec.ts`

**Interfaces:**
- Consumes: `VITE_API_BASE_URL` and backend-supplied relative `/api/...` paths.
- Produces: `apiUrl(path)` that resolves fetches and browser download links to the same API origin in both same-origin and split-origin deployments.

- [ ] **Step 1: Add failing URL-resolution tests**

  Test the required behavior:

  ```ts
  expect(apiUrl('/api/version', '')).toBe('/api/version')
  expect(apiUrl('/api/projects/p1/artifacts/a1/download', 'https://api.example.com')).toBe(
    'https://api.example.com/api/projects/p1/artifacts/a1/download'
  )
  expect(apiUrl('https://files.example.com/final.xlsx', 'https://api.example.com')).toBe(
    'https://files.example.com/final.xlsx'
  )
  ```

- [ ] **Step 2: Implement one URL resolver**

  In `frontend/src/apiClient.ts`:

  ```ts
  export const API = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

  export function apiUrl(path: string, base = API): string {
    if (!path) return ''
    if (/^https?:\/\//i.test(path)) return path
    const normalized = path.startsWith('/') ? path : `/${path}`
    return base ? `${base}${normalized}` : normalized
  }
  ```

  Make `api()` and chunk upload call this helper.

- [ ] **Step 3: Route every download link through `apiUrl`**

  Replace direct `href={file.download_url}` and hand-built `/api/...` values with `href={apiUrl(file.download_url)}`. Do not change backend response shapes.

- [ ] **Step 4: Add a split-origin E2E assertion**

  Build with `VITE_API_BASE_URL=https://api.example.test`, return a relative `download_url` from the mocked backend, and assert the rendered link begins with `https://api.example.test/api/`.

- [ ] **Step 5: Verify same-origin behavior has no regression**

  Run: `npm --prefix frontend run build`

  Run: `npm --prefix frontend run e2e -- --workers=1`

  Expected: build passes and all existing E2E tests remain green.

- [ ] **Step 6: Commit API URL normalization**

  ```bash
  git add frontend/src frontend/e2e/studio-ui-flow.spec.ts
  git commit -m "fix: resolve downloads against configured API origin"
  ```

### Task 4: Restore the operator's location after a full page refresh

**Files:**
- Create: `frontend/src/domain/workbenchSession.ts`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/hooks/useProjectActions.ts`
- Test: `frontend/e2e/studio-ui-flow.spec.ts`

**Interfaces:**
- Consumes: current `projectId`, `view`, `tab`, `step` and the project IDs returned by `/api/projects`.
- Produces: sanitized device-local session state; it is navigation state only and never caches API project/run/artifact data.

- [ ] **Step 1: Add a failing reload test**

  The E2E test creates two projects, selects the older project, enters the delivery Tab or a wizard step, reloads the page, and asserts the same project and location are restored while project/run data is fetched again from the API.

- [ ] **Step 2: Implement a narrow session schema**

  ```ts
  export interface WorkbenchSession {
    projectId: string
    view: 'overview' | 'wizard' | 'quick' | 'announcement'
    tab: 'meta' | 'assets' | 'translation' | 'qa' | 'delivery'
    step: number
  }
  ```

  Store only this schema in `localStorage`. Clamp `step` to `1..9`, reject unknown enum values, and ignore a stored project ID that is absent from the server response.

- [ ] **Step 3: Restore before selecting the default project**

  `refreshProjects()` must prefer the explicit `selectId`, then a valid saved `projectId`, then the current ref, then the first server project.

- [ ] **Step 4: Persist location changes without persisting API data**

  Add one effect in `main.tsx` that writes the session whenever `currentId/view/tab/step` changes. Do not store projects, runs, artifacts, deliverables or settings.

- [ ] **Step 5: Re-run reload and polling coverage**

  Run: `npm --prefix frontend run e2e -- --workers=1`

  Expected: reload restores location; the existing external-project refresh and active-run polling tests remain green.

- [ ] **Step 6: Commit refresh restoration**

  ```bash
  git add frontend/src/domain/workbenchSession.ts frontend/src/main.tsx frontend/src/hooks/useProjectActions.ts frontend/e2e/studio-ui-flow.spec.ts
  git commit -m "fix: restore workbench location after reload"
  ```

### Task 5: Prove persistence across backend restart and release switch

**Files:**
- Create: `scripts/restart_persistence_check.py`
- Modify: `docs/STABILITY_TEST_LIST.md`
- Test: `scripts/restart_persistence_check.py`

**Interfaces:**
- Consumes: public base URL plus a controlled service restart command supplied by the operator.
- Produces: evidence that database rows and real files survive backend restart and code-release switch.

- [ ] **Step 1: Create a probe project and upload fixture**

  Record project ID, artifact ID, upload SHA-256 and initial `/api/version` response in a temporary JSON evidence file.

- [ ] **Step 2: Require an explicit restart boundary**

  The script pauses with a machine-readable `ready_for_restart=true` state or accepts `--restart-command`. It must never restart an unspecified production service.

- [ ] **Step 3: Verify post-restart invariants**

  Assert:

  ```text
  data_root unchanged
  project still returned by /api/projects/{id}
  artifact exists=true
  artifact download HTTP 200
  downloaded SHA-256 equals uploaded SHA-256
  /api/health database.connected=true
  /api/health storage.data_root_writable=true
  /api/health storage.uploads_writable=true
  ```

- [ ] **Step 4: Verify translation cache placement**

  After a small fake-provider translation run in an isolated environment, assert the project-scoped `.translation_cache/en.jsonl` remains under `LWS_DATA_ROOT` and is still read after restart.

- [ ] **Step 5: Run against a staging deployment**

  Run: `python3.11 scripts/restart_persistence_check.py --base-url https://staging.example.com --restart-command "sudo systemctl restart lws"`

  Expected: all invariants pass and the temporary project is removed in `finally`.

- [ ] **Step 6: Commit the restart gate**

  ```bash
  git add scripts/restart_persistence_check.py docs/STABILITY_TEST_LIST.md
  git commit -m "test: verify upload and artifact persistence across restart"
  ```

### Task 6: Build a clean deployment artifact

**Files:**
- Modify: `scripts/build_release_package.py`
- Modify: `docs/CLOUD_DEPLOYMENT.md`
- Test: `scripts/build_release_package.py`

**Interfaces:**
- Consumes: a validated clean source tree and built `frontend/dist`.
- Produces: a versioned release archive that includes deployment templates but excludes all private runtime state.

- [ ] **Step 1: Add deployment files to the release manifest**

  Require `deploy/lws.service`, `deploy/nginx.conf.template`, `deploy/install.sh`, `deploy/lws.env.example`, `start-lws.sh`, `frontend/dist`, `VERSION`, backend and workflow runtime dependencies.

- [ ] **Step 2: Keep secrets out by default**

  Remove the normal deployment path's reliance on `--settings-file`. If the option remains for private handoff, mark the archive as private and never use it for GitHub/Sites publishing.

- [ ] **Step 3: Build from a clean staging tree**

  Run:

  ```powershell
  npm --prefix frontend ci
  npm --prefix frontend run build
  python scripts/build_release_package.py
  ```

- [ ] **Step 4: Inspect archive membership**

  Fail if the archive contains any of:

  ```text
  settings.local.json
  *.sqlite3
  projects/
  runs/
  uploads/
  artifacts/
  .git/
  node_modules/
  .local-logs/
  .tmp/
  ```

- [ ] **Step 5: Install the exact archive on staging and run all public gates**

  Run deployment check, restart persistence check and `scripts/stability_check.py` through the staging HTTPS origin.

- [ ] **Step 6: Commit packaging changes**

  ```bash
  git add scripts/build_release_package.py docs/CLOUD_DEPLOYMENT.md
  git commit -m "build: package reproducible online deployment"
  ```

### Task 7: Optional Sites frontend handoff

**Files:**
- Create or modify according to the Sites hosting contract after Tasks 1-6 pass.
- Modify: `frontend/vite.config.ts` only if the selected Sites build requires a different public base.
- Create: `.openai/hosting.json` only through the Sites creation flow; store only the Sites project ID and logical bindings.

**Interfaces:**
- Consumes: a healthy external FastAPI staging URL and the API URL resolver from Task 3.
- Produces: a Sites-hosted frontend that reaches the same persistent FastAPI backend without exposing `settings.local.json`.

- [ ] **Step 1: Confirm the backend is independently healthy**

  Do not publish the frontend until the external API passes `/api/version`, `/api/health`, diagnostic upload, artifact download and restart persistence.

- [ ] **Step 2: Choose one connection model**

  Preferred: Sites/Worker proxies `/api/*` to the external backend so the browser remains same-origin. Fallback: build with `VITE_API_BASE_URL=https://api.lws.internal.example` and set `LWS_CORS_ORIGINS` to the exact Sites origin.

- [ ] **Step 3: Protect the backend**

  Use private Sites access plus a protected backend ingress (Cloudflare Access, reverse-proxy authentication or an equivalent internal access gate). A public unauthenticated FastAPI endpoint would expose the server-side provider budget and all projects.

- [ ] **Step 4: Build and publish the exact validated frontend**

  Run the Sites validation/build path, publish privately, then poll deployment status to success.

- [ ] **Step 5: Re-run public-origin acceptance**

  Execute `deployment_check.py` and the browser E2E reload/upload/download path against the deployed Sites URL, not against the backend URL.

---

## Final Acceptance Gate

Run in this order; do not run pytest and Playwright in parallel when they share a data root:

```powershell
python -m pytest -q
python -m compileall -q backend workflow scripts
python -m ruff check backend/app backend/tests scripts --select E9,F
npm --prefix frontend run build
npm --prefix frontend run e2e -- --workers=1
```

Then run against staging HTTPS:

```bash
python3.11 scripts/deployment_check.py --base-url "$LWS_STAGING_URL" --require-cloud --require-provider --expect-version "$(cat VERSION)" --check-frontend-assets
python3.11 scripts/stability_check.py --base-url "$LWS_STAGING_URL"
python3.11 scripts/restart_persistence_check.py --base-url "$LWS_STAGING_URL" --restart-command "sudo systemctl restart lws"
```

Acceptance requires all of the following:

- The page and `/api/version` report the same version and Git SHA.
- A real upload is readable by the backend and remains downloadable after service restart.
- A background task remains visible after browser reload; the user returns to the same project and work location.
- Final outputs and QA summaries download from the user's frontend origin without 404 or cross-origin leakage.
- `index.html` and API are not cached; hashed assets are immutable.
- `settings.local.json` is loaded from the persistent server data directory and is absent from the release archive and frontend.
- SQLite, project files, run files, translation cache and delivery files all live under one persistent `LWS_DATA_ROOT`.
- Only one FastAPI worker is active.
- The public endpoint has an access gate appropriate for an internal localization operations team.

## Recommended Execution Order

1. Obtain the actual broken deployment URL and run Task 1 to turn symptoms into a named failing boundary.
2. Implement Tasks 2, 5 and 6 to make the full-stack VPS deployment reliable without touching the visual frontend.
3. Implement Task 4 because refresh-state loss is a confirmed frontend gap.
4. Implement Task 3 only if frontend and API will be on different origins or Sites remains a hard requirement.
5. Use Task 7 only after the full backend/persistence gates pass.
