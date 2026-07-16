# 账号与权限系统设计计划（2026-07-15）

> 目标：线上（cloud）部署提供账号登录和三档权限；本地（local）模式默认保持现状免登录，可用环境变量开启。
> 边界：不改 SQLite 技术栈；不改翻译/QA/交付业务语义；不接入飞书；公司账号体系（SSO）只预留接口、本期不实现。
> 前置：本计划是 2026-07-08 多人并发计划的续篇。该计划明确"不做鉴权"，本计划补上鉴权层，复用其项目级锁与留痕地基。
> 执行模式：fable5 主线程调度+验收，sonnet-5 / gpt-5.6-sol 子 agent 执行批次；隔离 worktree `feature/account-permission-system`，每批全量回归后合并。

## 执行进度

- [x] A1 批 1（2026-07-15，sonnet-5，commit 4d56791）：users/sessions 表、argon2id、session 签发、登录防爆破、/api/auth/login|logout|me。
- [x] A1 批 2（2026-07-15，gpt-5.6-sol，commit bd4d12a）：`LWS_AUTH_MODE` 开关（cloud 默认 required）、强制登录中间件（白名单仅 login/logout/me/version/health）、初始管理员 fail-closed 引导、scripts/create_admin.py。验收返工一次：upload-readability 端点因写盘风险移出免登录白名单，deployment_check 的登录适配留给 A4。
- [x] A1 批 3（2026-07-15，sonnet-5，commit 7369eb0）：require_admin 依赖（authz.py）、/api/users 管理 API（无 DELETE，停用代替）、停用/重置密码即撤销 session、/api/auth/change-password、首登强制改密门禁（403）。
- [x] A2 权限执行层（2026-07-15，commit a4c25ed 批1+2、57ff6c2 批3+4）：capability 常量与角色映射、`route_capabilities.py` 一张表挂全部 ~104 条 `/api/` 路由并 fail-closed 兜底、项目成员表 + 成员管理 API + 列表按成员过滤、三档角色权限矩阵 e2e 覆盖、下载/artifact 直链权限复核。裁决记录见下一行。
  - **裁决（2026-07-15）**：`/glossary/extract`、`/glossary/batches/*`、`/glossary/candidates/*` 维持 `assets:curate`（member 不能主动修改术语库，确认候选即写入术语库必须封锁）；翻译向导第 5 步（术语候选，`StepFreqV2`）对无 `assets:curate` 的用户降级为只读——隐藏扫描/补译/确认/跳过/编辑入口，向导前进判定忽略 pending 候选数。详见 `docs/ROUTE_CAPABILITIES.md`。
- [x] A3 前端（2026-07-15，commit 0270c1a 批1+2、399729b 批3+4）：登录页 + apiClient 统一 401 跳登录 + `credentials: include`、能力驱动的 UI 显隐（隐藏删项目/术语归档编辑/项目资料维护入口）、管理员用户管理面板、项目成员管理面板、`X-Operator` 昵称设置在认证开启时隐藏、认证专用 e2e 套件（`npm run e2e:auth`）覆盖三档角色主路径与越权拒绝。
- [x] A4 部署收尾（2026-07-15，本批）：`check.py`/`scripts/deployment_check.py`、`scripts/stability_check.py` 加 `--auth-user/--auth-password` 登录支持（`scripts/deployment_auth.py` 公共函数）与 `auth_fail_closed` 未登录 401 自检项；`operator_audit.log` 补 `login`/`logout` 事件（登录失败不记）；`docs/CLOUD_DEPLOYMENT.md`/`docs/STABILITY_TEST_LIST.md`/`README.md` 更新；版本联动 1.3.1 → 1.4.0。

- [x] 完整验收（2026-07-15，fable5 主线程，commit ae3d81d）：全量 `pytest -q backend/tests` 328 passed；`npm run build` 零错误；全量 e2e（认证关闭）60 passed；`npm run e2e:auth` 5 passed；对 `LWS_AUTH_MODE=required` 真实后端跑 21 项跨角色越权冒烟全过（未登录 401、member 越权 403、非成员 404、停用即失效、admin 直通）；`check.py --auth-user` 全链路 exit=0。验收期间发现并修复一处 e2e 竞态：studio-ui-flow 提示词保存后未等 PATCH 完成就读回断言（基线偶发、本分支因时序变化转为稳定失败，非产品代码回归），已改为 `waitForResponse` 等待保存完成。

A1 遗留（进 A2/A4 待办）：conftest 缺少对 `importlib.reload(main_module)` 全局状态泄漏的通用防护（现只在 test_users_admin.py 局部处理）；create_admin.py CLI 路径不写审计；密码策略仅长度下限；防爆破为进程内存态（单实例部署下可接受）。

---

## 0. 事实基线（2026-07-15 探查）

- 身份现状：无任何 user/session/owner 概念。`operator_context.py` 只透传浏览器本地昵称（`X-Operator` 头），"不校验、不授权"，前端在 `apiClient.ts:96` 统一注入。
- 模式判定：`routers/system.py:39` `_deployment_mode()` 已区分 `local`/`cloud`（`LWS_DEPLOYMENT_MODE` 或 `/data/web/` 路径推断），云端已用它 403 掉 `PATCH /api/settings`（system.py:228）。认证开关可复用同一机制。
- 路由面：9 个 router 共约 104 个路由。破坏性操作集中：删项目 `projects.py:234`、术语增删改 `glossary.py:115` 等、归档译文增删改 `translations.py:45/56/65`。
- 归档双路径：任务交付自动写归档走 workflow 内部（`source_type=qa_passed` / `delivered_with_issues`），手动维护走 `/api/projects/{id}/translations*` REST 入口。两者代码路径独立，可只封手动入口。
- DB：SQLite 单文件，`db.py` 建表处（projects/glossary_terms/translation_entries/runs/artifacts/events/announcement_*/job_leases）无用户外键。events 表是 run 级过程日志，非操作审计；项目删除审计走 `operator_audit.log`（append-only JSONL）。
- 前端：单页应用（无路由库），`main.tsx` 为主壳，已有 `SettingsModal`、`DeleteProjectModal`、`ActiveJobsPanel` 等组件化拆分；401 处理、登录页、权限显隐均需新建。
- CORS：`allow_credentials=True` 已开（main.py:45），cookie 方案可行。

## 1. 需求确认结果（与用户对齐）

| # | 决策点 | 结论 |
|---|---|---|
| 1 | 生效范围 | 云端强制登录；本地默认免登录（视为管理员），`LWS_AUTH_MODE=required` 可强制开启 |
| 2 | 身份来源 | 自建账号密码体系；不接飞书；公司账号体系后续可能接入，预留 provider 接口 |
| 3 | 三档角色 | 1 档管理员 / 2 档项目运营 / 3 档普通用户，角色为全局属性 |
| 4 | 项目可见性 | 运营与普通用户均按"项目成员"分配可见（同一套成员机制，档位决定能力）（已确认） |
| 5 | 普通用户建项目 | 可以创建项目，创建后自动成为该项目成员（已确认） |
| 6 | 公告外文本 | 属于三档可用的基础功能，与翻译任务/快速任务同级（已确认） |
| 7 | 成员分配 | 运营可管理自己成员项目的成员，管理员管全部（已确认） |

## 2. 权限模型

### 2.1 角色与能力矩阵

角色是**全局档位**（一个用户只有一个角色）；项目可见性由 `project_members` 成员表决定；能力 = 角色 × 是否项目成员。

| 能力域 | 管理员 | 项目运营（成员项目） | 普通用户（成员项目) |
|---|---|---|---|
| 查看项目列表/详情 | 全部项目 | 仅成员项目 | 仅成员项目 |
| 创建项目 | ✅ | ✅ | ✅（创建后自动成为成员） |
| 删除项目 | ✅ | ✅ | ❌（含自己创建的项目） |
| 项目资料/元信息/提示词维护 | ✅ | ✅ | ❌ |
| 翻译任务（完整向导） | ✅ | ✅ | ✅ |
| 快速任务 | ✅ | ✅ | ✅ |
| 公告外文本工作流 | ✅ | ✅ | ✅（属基础功能；手动删改仍封锁） |
| 术语库：查看/导出 | ✅ | ✅ | ✅ |
| 术语库：增删改/导入/AI 补充 | ✅ | ✅ | ❌ |
| 归档译文：查看/导出 | ✅ | ✅ | ✅ |
| 归档译文：手动增删改/导入 | ✅ | ✅ | ❌ |
| 归档自动写入（交付管线） | 系统行为，不受操作者档位限制 | 同左 | 同左 |
| 项目成员管理 | ✅ 全部 | ✅ 自己的成员项目 | ❌（含自己创建的项目，需运营/管理员分配他人） |
| 用户管理（建号/停用/重置密码/改档位） | ✅ | ❌ | ❌ |
| 全局设置（provider/api key） | ✅（本地模式；云端仍走配置文件） | ❌ | ❌ |

要点：

- **普通用户创建的项目也遵守三档规则**：创建者自动成为成员、可跑任务，但不能删项目、不能手动维护术语/归档、不能给项目加人——需要运营或管理员接手分配。这是刻意的："能创建但不能删除"防止误删，同时把资产维护权收在运营档。若实际使用中发现太别扭，可在后续版本给"创建者"单独放开成员管理权（数据模型已留 `added_by` 字段，无需迁移）。
- **"自动归档"不做特殊授权**：归档写入发生在交付管线内部，属于系统行为。普通用户发起翻译任务 → QA 通过 → 自动写归档，全程合法；封锁的只是 `/translations` 的手动 POST/PATCH/DELETE 入口。术语库同理（任务过程中的术语快照生成不受影响，封的是手动维护入口）。
- **capability 白名单而非角色散写**：定义一组能力常量（`project:read`、`task:run`、`assets:curate`、`project:manage`、`admin:*`），每个路由声明所需能力，角色映射到能力集合。审查时看一张表，不用翻 104 个路由。

### 2.2 数据模型（SQLite 新增三张表）

```sql
users (
  id TEXT PRIMARY KEY,            -- uuid
  username TEXT UNIQUE NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  password_hash TEXT NOT NULL,    -- argon2id (passlib)
  role TEXT NOT NULL,             -- 'admin' | 'ops' | 'member'
  status TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'disabled'
  external_id TEXT DEFAULT '',    -- 预留：公司账号体系映射
  must_change_password INTEGER NOT NULL DEFAULT 0,
  created_at TEXT, last_login_at TEXT
)

sessions (
  token_hash TEXT PRIMARY KEY,    -- 只存哈希，泄库不泄票
  user_id TEXT NOT NULL,
  created_at TEXT, expires_at TEXT, last_seen_at TEXT
)

project_members (
  project_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  added_by TEXT NOT NULL DEFAULT '',
  created_at TEXT,
  PRIMARY KEY (project_id, user_id)
)
```

设计取舍：

- **服务端 session + HttpOnly cookie**，不用 JWT。单实例 + SQLite 场景下 session 表最简单，且可即时吊销（停用账号立刻生效）。cookie 属性：`HttpOnly; SameSite=Lax; Secure`（云端）。同源 SPA + SameSite=Lax 足以覆盖 CSRF 基线，破坏性操作全部走非 GET。
- **密码**：passlib argon2id；管理员建号发初始密码，`must_change_password=1` 强制首登改密；忘记密码由管理员重置，不做邮件流。
- **登录防爆破**：按 username+IP 的滑动窗口失败计数（内存即可），超限临时锁定。
- **SSO 预留**：认证入口抽象为 `AuthProvider`（本期只有 `LocalPasswordProvider`）；`users.external_id` 预留映射位。接入公司账号时新增 provider，不动权限层。

### 2.3 模式与开关

```text
cloud 模式           → 强制登录（无有效 session 的 /api/* 一律 401，除 /api/auth/* 和健康检查）
local 模式（默认）    → 免登录，请求视为内置管理员身份 "local-admin"，行为与现状完全一致
local + LWS_AUTH_MODE=required → 与 cloud 相同的强制登录
```

- 管理员引导：首次以强制登录模式启动且 users 表为空时，从 `LWS_ADMIN_USER` / `LWS_ADMIN_PASSWORD` 环境变量创建初始管理员（或提供 `scripts/create_admin.py`）；两者都缺则启动报错，不留后门。
- 存量数据迁移：已有项目无 owner。开启认证后默认只有管理员可见，由管理员逐个分配成员。不做自动猜测归属。
- `X-Operator` 留痕：认证关闭时保留现状；认证开启时忽略该头，`operator_context` 直接取登录用户 display_name——现有全部留痕/审计调用点零改动升级为真实身份。

### 2.4 后端执行层

- FastAPI 依赖链：`get_current_user`（session cookie → users 行，模式开关在此短路）→ `require_capability(cap)` → 涉及项目的再走 `require_project_access(project_id)`。
- 列表类接口（`GET /api/projects` 等）按成员关系过滤而不是 403，非成员项目直接不可见（防枚举）。
- run/artifact/glossary/translation/announcement 等子资源全部经 project_id 归属校验（现有 `_require_project_*` helper 正好是挂载点）。
- 下载链接（`download_urls.py`）需要复核：如果是无鉴权直链，改为经权限校验的流式响应或短时效签名 URL。

## 3. 阶段与批次

### 阶段 A1：身份地基（纯后端，开关默认关，可独立合并）

- 批 1：建表 + `auth` 模块（密码哈希、session 签发/校验/清理、登录防爆破）；`POST /api/auth/login`、`POST /api/auth/logout`、`GET /api/auth/me`。
- 批 2：认证中间件/依赖 + 模式开关（cloud 强制 / local 免登 / `LWS_AUTH_MODE` 覆盖）+ 初始管理员引导 + `scripts/create_admin.py`。
- 批 3：用户管理 API（管理员专属）：建号、停用/启用、重置密码、改档位、列表；首登强制改密。
- 回归：开关关闭时全量现有 pytest 零改动通过（证明默认行为不变）。

### 阶段 A2：权限执行层

- 批 1：capability 常量 + 角色→能力映射 + 路由能力标注清单（一张 104 路由的分类表，进 docs，作为评审依据）。
- 批 2：项目成员表 + 成员管理 API + 列表接口按成员过滤 + `require_project_access` 接入全部 `_require_project_*` 调用点。
- 批 3：破坏性入口封锁：删项目、术语增删改/导入/AI 补充、归档译文手动增删改/导入、项目资料/元信息/提示词维护，按矩阵逐条落 `require_capability`；公告外文本对三档放开（任务流本身不属破坏性操作）。
- 批 4：下载/artifact 直链权限复核与修补。
- 回归测试：每档角色一套 API 权限矩阵测试（member 发翻译任务全流程含自动归档成功；member 手动 DELETE 术语/归档/项目得 403；非成员项目 404/不可见；ops 删项目成功；停用账号 session 立即失效）。

### 阶段 A3：前端

- 批 1：登录页（App 壳外的 gate 组件）+ `apiClient` 统一 401 → 跳登录；`credentials: include`；顶部当前用户徽标 + 登出；首登改密流程。
- 批 2：权限感知 UI：以 `GET /api/auth/me` 返回的 role + capabilities 驱动显隐——member 隐藏删项目按钮、术语/归档编辑控件、项目资料维护入口；翻译任务/快速任务/公告工作流保持完整可用；只读态展示保持可见可导出。
- 批 3：管理面板：用户管理页（管理员）+ 项目成员管理面板（管理员/运营）。
- 批 4：`X-Operator` 昵称设置在认证开启时隐藏（身份来自登录态）。
- e2e：三档角色各一条主路径用例 + 越权操作被 UI 和 API 双重拒绝。

### 阶段 A4：部署收尾

- CLOUD_DEPLOYMENT.md：新增认证配置段（`LWS_ADMIN_USER/PASSWORD`、cookie Secure 要求 HTTPS、反代注意事项）；STABILITY_TEST_LIST 增加认证/越权测试项。
- `check.py` / `stability_check.py` 适配：支持 `--auth-user/--auth-password` 登录后再跑冒烟；未登录访问核心 API 必须 401 作为部署自检项。
- 审计增强：`operator_audit.log` 记录 login/logout/建号/改档位/成员变更。
- Tier D 验收 + 版本联动（MINOR）。

## 4. 验证分层

- 每批：Tier A + auth/权限聚焦测试。
- 阶段末：Tier C 全量（pytest + e2e）。
- A1 合并后专项验证：**开关关闭时行为与主干完全一致**（这是本计划最重要的回归承诺）。
- A4 末：Tier D（deployment_check + stability_check + 越权冒烟）。

## 5. 完成标准

- [x] 云端部署未登录访问任何业务 API 返回 401；登录后按档位工作。(A1-A2 后端强制 + A4 `check.py` `auth_fail_closed` 自检项覆盖)
- [x] 本地模式默认零感知：不建号、不登录，行为与当前版本一致。(`test_local_mode_defaults_to_auth_off_and_exposes_synthetic_admin` 等回归测试)
- [x] member 完整跑通翻译任务/快速任务并自动写归档；手动删项目/改术语/改归档全部 403 且 UI 无入口。(A2 矩阵测试 + A3 UI 显隐)
- [x] ops 仅见成员项目，可维护术语/归档、可删项目；admin 可见全部并可管理用户和成员。(A2 成员过滤 + A3 管理面板)
- [x] 停用账号后其 session 立即失效。(`db.delete_sessions_for_user`，A1 批 3)
- [x] 密码仅存 argon2id 哈希；session 票据仅存哈希；登录有防爆破。(A1 批 1)
- [x] 全量 pytest + e2e 绿；CLOUD_DEPLOYMENT/STABILITY_TEST_LIST 更新；权限矩阵表进 docs。(A4：`pytest -q backend/tests` 328 passed；`npm run e2e:auth` 5 passed；文档见本批改动)

## 6. 风险与对策

- **104 路由漏标能力** → 兜底策略：认证开启时未标注路由默认要求 `admin`（fail-closed），漏标只会过严不会过宽；路由分类表评审 + 矩阵测试双保险。
- **下载直链绕过权限** → A2 批 4 专项排查 `download_urls.py` 与 artifact 静态服务路径，宁可全部改走鉴权流式响应。
- **与并发计划的交互** → 权限层只在请求入口，不触碰 jobs/lease/限流；两计划改动面无交集，可并行。
- **本地模式回归** → "local-admin 内置身份"路径必须与现状字节级等价，A1 用全量旧测试守护。
- **SSO 未来接入返工** → AuthProvider 抽象 + external_id 预留；权限层完全不感知认证方式，接 SSO 时零改动。

## 7. 待确认问题

前四项决策点已于 2026-07-15 与用户确认完毕（见 §1 表）。剩余：

1. 公司账号体系的形态（OIDC / LDAP / 自研网关）？——只影响未来 AuthProvider 实现，本期只做接口预留，不需要答案。
