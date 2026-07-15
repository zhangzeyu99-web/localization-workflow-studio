# 路由能力分类表（A2 批 1+2）

> 权威规范：`docs/superpowers/plans/2026-07-15-account-permission-system.md` §2.1 能力矩阵。
> 执行层：`backend/app/route_capabilities.py`（`CAPABILITY_BY_ROUTE` + `EXEMPT_ROUTES`），由
> `backend/app/main.py` 通过 `app.include_router(api_router, dependencies=[Depends(enforce_route_access)])`
> 统一挂载，`route_capabilities.assert_full_route_coverage(app)` 在应用构建时做 fail-closed 校验：
> 任何 `/api/` 路由若不在下表（或豁免表）中登记，启动即报错。
>
> 本文档与源码表逐条对应（114 条路由，含项目成员管理 4 条）；如两者出现差异，以源码表为准，
> 应同步更新本文档。

## 能力定义

| 能力 | 说明 |
|---|---|
| `project:read` | 查看项目及其子资源（详情、列表、导出、只读进度/状态）。admin/ops/member 均具备。 |
| `task:run` | 发起/操作翻译任务、快速任务、公告工作流；上传资料供任务使用；下载任务交付物。admin/ops/member 均具备。 |
| `assets:curate` | 术语库/归档译文的手动增删改/导入、AI 术语补充；项目资料/元信息/提示词（harness）维护。仅 admin/ops。 |
| `project:manage` | 删除项目、管理项目成员。仅 admin/ops（ops 仅限自己所在的成员项目，由项目成员校验兜底）。 |
| `admin:*` | 用户管理、全局设置写操作、系统诊断写操作。仅 admin。 |

角色 → 能力：admin = 全部；ops = `{project:read, task:run, assets:curate, project:manage}`；
member = `{project:read, task:run}`。

## 项目归属校验

除能力检查外，携带 `project_id`（直接路径参数，或通过 `run_id`/`task_id`/`artifact_id` 反查其所属项目）
的路由还会做项目成员校验：admin 直通；非 admin 必须是该项目的 `project_members` 行，否则返回 **404**
（而非 403，防止通过状态码枚举项目是否存在）。`GET /api/runs`（无 `project_id` 查询参数时）和
`GET /api/projects` 改为按成员关系过滤列表，而不是逐项 404。`POST /api/runs`（`project_id` 只在请求体中）
在路由处理函数内显式调用了同一个 `require_project_access`，因为集中网关只检查路径参数。

## 豁免路由（无需能力）

| 方法 | 路径 | 理由 |
|---|---|---|
| POST | `/api/auth/login` | 登录入口本身，调用者此时必然没有 session |
| POST | `/api/auth/logout` | 任何已登录身份都能登出自己 |
| GET | `/api/auth/me` | 前端探测登录态本身，不含业务数据 |
| POST | `/api/auth/change-password` | 首登强制改密必须在拿到任何能力之前可用 |
| GET | `/api/version` | 只读系统版本信息，未登录也可探活（`main.py _PRELOGIN_API_ENDPOINTS`） |
| GET | `/api/health` | 只读健康检查，部署探活需要，未登录也可访问 |
| GET | `/api/users` | 已由 `users.router` 的 `Depends(require_admin)` 保护 |
| POST | `/api/users` | 同上 |
| PATCH | `/api/users/{user_id}` | 同上 |
| POST | `/api/users/{user_id}/reset-password` | 同上 |

## 路由分类表

### system（health/version/settings/languages/诊断）

| 方法 | 路径 | 能力 | 依据 |
|---|---|---|---|
| GET | `/api/health` | 豁免 | 见上表 |
| GET | `/api/version` | 豁免 | 见上表 |
| POST | `/api/diagnostics/upload-readability` | `admin:*` | 系统诊断写操作（写盘自检），矩阵归类为全局设置/诊断写操作 |
| GET | `/api/import-templates/{kind}` | `project:read` | 只读静态模板文件，不含项目数据，仍要求登录防匿名探测 |
| GET | `/api/settings` | `project:read` | 供全部角色的任务向导读取当前 provider/批量参数等非密钥配置 |
| PATCH | `/api/settings` | `admin:*` | 全局 provider/api key 配置，矩阵明确仅管理员（云端还另有部署模式 403） |
| GET | `/api/system/active-jobs` | `project:read` | 跨项目列表，处理函数内按成员项目过滤，非成员看不到别的项目的任务 |
| GET | `/api/languages` | `project:read` | 只读语言列表，无项目数据 |

### auth（豁免，自管）

见上豁免表；`backend/app/routers/auth.py` 全部路由豁免。

### users（豁免，已有 require_admin）

见上豁免表；`backend/app/routers/users.py` 的路由本身已用
`APIRouter(dependencies=[Depends(require_admin)])` 保护，此处只是把它们登记进豁免表以通过启动期扫描。

### projects（`backend/app/routers/projects.py`）

| 方法 | 路径 | 能力 | 依据 |
|---|---|---|---|
| GET | `/api/projects` | `project:read` | 查看项目列表；处理函数按成员关系过滤（非 admin 只见自己的成员项目） |
| POST | `/api/projects` | `project:read` | 三档角色均可建项目（矩阵），创建时项目尚不存在，无法做成员校验；创建成功后非 admin 创建者自动写入 `project_members` |
| GET | `/api/projects/{project_id}` | `project:read` | 查看项目详情 |
| PATCH | `/api/projects/{project_id}` | `assets:curate` | 项目资料/元信息/提示词维护 |
| DELETE | `/api/projects/{project_id}` | `project:manage` | 删除项目 |
| GET | `/api/projects/{project_id}/ai-input-summary` | `project:read` | 只读：AI 输入构成摘要 |
| POST | `/api/projects/{project_id}/analyze` | `assets:curate` | 生成/覆盖项目 profile、翻译提示词、brief（项目资料维护） |
| GET | `/api/projects/{project_id}/harness` | `project:read` | 只读；同一数据已随 `GET /api/projects/{id}` 的 `include_details=True` 一起返回，单独接口不应更严 |
| PATCH | `/api/projects/{project_id}/harness` | `assets:curate` | 项目规则包（harness）维护 |
| GET | `/api/projects/{project_id}/assets` | `project:read` | 查看项目资料/上传文件列表 |
| POST | `/api/projects/{project_id}/files` | `task:run` | 上传资料供任务使用 |
| POST | `/api/projects/{project_id}/files/chunk` | `task:run` | 同上（分片上传） |
| GET | `/api/projects/{project_id}/artifacts/{artifact_id}/download` | `project:read` | 只读下载 |
| GET | `/api/projects/{project_id}/artifacts/{artifact_id}/translation-readiness` | `project:read` | 只读检查 |
| GET | `/api/projects/{project_id}/artifacts/{artifact_id}/translation-targets` | `project:read` | 只读检查 |
| GET | `/api/projects/{project_id}/improvements` | `project:read` | 只读：QA 改进建议队列 |
| POST | `/api/projects/{project_id}/improvements` | `assets:curate` | 写入项目改进建议（进而可应用到 harness），归入项目资料维护 |

### members（`backend/app/routers/members.py`，本批新增）

| 方法 | 路径 | 能力 | 依据 |
|---|---|---|---|
| GET | `/api/projects/{project_id}/members` | `project:read` | 成员列表对该项目成员可见 |
| GET | `/api/projects/{project_id}/members/addable` | `project:manage` | 返回可添加的 active 非成员账号；ops 只能查询自己所在的成员项目 |
| POST | `/api/projects/{project_id}/members` | `project:manage` | 添加成员；ops 只能管理自己所在的成员项目（由项目归属校验兜底） |
| DELETE | `/api/projects/{project_id}/members/{user_id}` | `project:manage` | 移除成员；同上 |

### glossary（`backend/app/routers/glossary.py`）

| 方法 | 路径 | 能力 | 依据 |
|---|---|---|---|
| GET | `/api/projects/{project_id}/glossary` | `project:read` | 查看术语 |
| POST | `/api/projects/{project_id}/glossary` | `assets:curate` | 手动新增术语 |
| GET | `/api/projects/{project_id}/glossary/wide` | `project:read` | 查看（宽表视图） |
| GET | `/api/projects/{project_id}/glossary/batches` | `project:read` | 查看提取批次/候选词 |
| PATCH | `/api/projects/{project_id}/glossary/candidates/{candidate_id}` | `assets:curate` | 编辑候选词（AI 提取产物，采纳前维护） |
| POST | `/api/projects/{project_id}/glossary/batches/{batch_id}/accept` | `assets:curate` | 采纳候选词写入主术语表 |
| POST | `/api/projects/{project_id}/glossary/batches/{batch_id}/translate-missing` | `assets:curate` | AI 补充候选词译文 |
| POST | `/api/projects/{project_id}/glossary/batches/{batch_id}/reject` | `assets:curate` | 拒绝候选词（维护动作） |
| PATCH | `/api/projects/{project_id}/glossary/{term_id}` | `assets:curate` | 编辑术语 |
| DELETE | `/api/projects/{project_id}/glossary/{term_id}` | `assets:curate` | 删除术语 |
| POST | `/api/projects/{project_id}/glossary/import-preview` | `assets:curate` | 导入前预览，与导入同一维护动作链路，拿不准按更严处理 |
| POST | `/api/projects/{project_id}/glossary/import` | `assets:curate` | 导入术语 |
| GET | `/api/projects/{project_id}/glossary/export` | `project:read` | 导出（只读） |
| POST | `/api/projects/{project_id}/glossary/extract` | `assets:curate` | 从项目资料 AI 提取术语候选（写入 `glossary_batches`/`glossary_candidates`），归入术语维护 |

### translations（归档译文，`backend/app/routers/translations.py`）

| 方法 | 路径 | 能力 | 依据 |
|---|---|---|---|
| GET | `/api/projects/{project_id}/translations` | `project:read` | 查看归档 |
| POST | `/api/projects/{project_id}/translations` | `assets:curate` | 手动新增归档条目 |
| GET | `/api/projects/{project_id}/translations/wide` | `project:read` | 查看（宽表视图） |
| PATCH | `/api/projects/{project_id}/translations/{entry_id}` | `assets:curate` | 手动编辑归档条目 |
| DELETE | `/api/projects/{project_id}/translations/{entry_id}` | `assets:curate` | 手动删除归档条目 |
| POST | `/api/projects/{project_id}/translations/import` | `assets:curate` | 导入归档 |
| GET | `/api/projects/{project_id}/translations/export` | `project:read` | 导出（只读） |

> 交付管线内部自动写归档（`source_type=qa_passed`/`delivered_with_issues`）走 workflow 内部函数，不经过
> 这些 REST 入口，因此不受本表限制——这是计划里明确的"系统行为，不受操作者档位限制"。

### delivery（`backend/app/routers/delivery.py`）

| 方法 | 路径 | 能力 | 依据 |
|---|---|---|---|
| GET | `/api/projects/{project_id}/deliverables` | `project:read` | 查看交付物列表 |
| POST | `/api/projects/{project_id}/delivery-package` | `task:run` | 生成交付包（任务流程的一步） |
| POST | `/api/projects/{project_id}/delivery-package/merged` | `task:run` | 生成合并交付包 |
| GET | `/api/projects/{project_id}/delivery/{filename}` | `task:run` | 交付下载，矩阵明确"交付下载"归 `task:run` |

### announcement（`backend/app/routers/announcement.py`）

公告外文本工作流对三档角色都开放（矩阵："公告外文本工作流 ✅ 全部档；手动删改仍封锁"）。以下所有
`/api/announcement-tasks/{task_id}/*` 步骤（提取术语、查词、准备、翻译、导入 AI 响应、应用、修复硬性
拦截、交付、取消）都是任务流水线内部步骤，产物落在任务自己的 run/artifact/metadata 里，**不会**直接写入
项目级 `glossary_terms`/`translation_entries` 主表（已读源码确认：`extract_announcement_terms`、
`import_announcement_terms`、AI 补充 `_apply_announcement_ai_supplement` 均只操作任务自身的
`announcement_tasks.metadata`/独立 artifact），因此统一归 `task:run` 而不是 `assets:curate`。

| 方法 | 路径 | 能力 | 依据 |
|---|---|---|---|
| POST | `/api/projects/{project_id}/announcement-lookup` (deprecated) | `task:run` | 旧版查词入口，任务流程步骤 |
| POST | `/api/projects/{project_id}/announcement-terms` | `task:run` | 生成公告术语包（任务级产物，非主术语表） |
| POST | `/api/projects/{project_id}/announcement-docx/prepare` (deprecated) | `task:run` | 旧版 DOCX 流程步骤 |
| POST | `/api/projects/{project_id}/announcement-docx/import-ai` (deprecated) | `task:run` | 同上 |
| POST | `/api/projects/{project_id}/announcement-docx/apply` (deprecated) | `task:run` | 同上 |
| POST | `/api/projects/{project_id}/announcement-docx/deliver` (deprecated) | `task:run` | 同上 |
| GET | `/api/projects/{project_id}/announcement-tasks` | `project:read` | 查看任务列表 |
| POST | `/api/projects/{project_id}/announcement-tasks` | `task:run` | 创建公告任务 |
| GET | `/api/announcement-tasks/{task_id}` | `project:read` | 查看任务详情（`task_id` 反查 `project_id`） |
| GET | `/api/announcement-tasks/{task_id}/ai-input-summary` | `project:read` | 只读：AI 输入摘要 |
| POST | `/api/announcement-tasks/{task_id}/cancel` | `task:run` | 取消任务 |
| POST | `/api/announcement-tasks/{task_id}/inspect-constraints` | `task:run` | 任务步骤：约束检查 |
| POST | `/api/announcement-tasks/{task_id}/extract-terms` | `task:run` | 任务步骤：提取术语（任务级产物） |
| POST | `/api/announcement-tasks/{task_id}/import-terms` | `task:run` | 任务步骤：导入术语表 |
| POST | `/api/announcement-tasks/{task_id}/lookup-translations` | `task:run` | 任务步骤：查历史译文 |
| POST | `/api/announcement-tasks/{task_id}/prepare` | `task:run` | 任务步骤：准备翻译 |
| POST | `/api/announcement-tasks/{task_id}/translate` | `task:run` | 任务步骤：同步翻译 |
| POST | `/api/announcement-tasks/{task_id}/translate/start` | `task:run` | 任务步骤：后台翻译启动 |
| POST | `/api/announcement-tasks/{task_id}/translate/resume` | `task:run` | 同上（续跑） |
| POST | `/api/announcement-tasks/{task_id}/translate/cancel` | `task:run` | 取消翻译 |
| POST | `/api/announcement-tasks/{task_id}/import-ai` | `task:run` | 任务步骤：导入 AI 响应 |
| POST | `/api/announcement-tasks/{task_id}/apply` | `task:run` | 任务步骤：应用翻译到输出文件 |
| POST | `/api/announcement-tasks/{task_id}/fix-hard-blockers` | `task:run` | 任务步骤：修复硬性拦截 |
| POST | `/api/announcement-tasks/{task_id}/deliver` | `task:run` | 任务交付（矩阵："交付下载"归 `task:run`） |

### runs + qa（`backend/app/routers/runs.py` + `backend/app/routers/qa.py`）

| 方法 | 路径 | 能力 | 依据 |
|---|---|---|---|
| POST | `/api/runs` | `task:run` | 发起任务；`project_id` 只在请求体中，处理函数内显式调用 `require_project_access` |
| GET | `/api/runs` | `project:read` | 无 `project_id` 查询参数时是跨项目列表，处理函数内按成员过滤；有 `project_id` 时显式校验 |
| GET | `/api/runs/{run_id}` | `project:read` | 查看 run 详情（`run_id` 反查 `project_id`） |
| GET | `/api/runs/{run_id}/ai-input-summary` | `project:read` | 只读 |
| GET | `/api/runs/{run_id}/events` | `project:read` | 只读事件日志 |
| POST | `/api/runs/{run_id}/qa` | `task:run` | 同步跑 QA |
| POST | `/api/runs/{run_id}/qa/start` | `task:run` | 后台跑 QA |
| POST | `/api/runs/{run_id}/qa/cancel` | `task:run` | 取消 QA |
| POST | `/api/projects/{project_id}/multilingual/qa/start` | `task:run` | 多语言 QA 队列 |
| GET | `/api/runs/{run_id}/quality-issues` | `project:read` | 只读 QA 结果 |
| POST | `/api/runs/{run_id}/manual-fixes` | `task:run` | 任务内工作簿的人工修复（属任务流程，非归档主表编辑） |
| POST | `/api/runs/{run_id}/manual-fixes/start` | `task:run` | 同上（异步版） |
| POST | `/api/runs/{run_id}/model-fixes` | `task:run` | 任务内模型修复 |
| POST | `/api/runs/{run_id}/model-fixes/start` | `task:run` | 同上（异步版） |
| POST | `/api/runs/{run_id}/semantic-qa` | `task:run` | 生成语义 QA 上下文 |
| GET | `/api/projects/{project_id}/improvements` | `project:read` | 见 projects 分组 |
| POST | `/api/projects/{project_id}/improvements` | `assets:curate` | 见 projects 分组 |
| POST | `/api/runs/{run_id}/improvement-review` | `assets:curate` | 由 QA 结果自动生成改进建议，写入项目级建议队列，归入项目资料维护而非任务操作 |
| POST | `/api/projects/{project_id}/multilingual/translate/start` | `task:run` | 多语言翻译队列 |
| GET | `/api/projects/{project_id}/multilingual/status` | `project:read` | 只读队列状态 |
| POST | `/api/runs/{run_id}/translate` | `task:run` | 同步翻译 |
| POST | `/api/runs/{run_id}/translate/start` | `task:run` | 后台翻译 |
| POST | `/api/runs/{run_id}/translate/resume` | `task:run` | 续跑 |
| POST | `/api/runs/{run_id}/translate/cancel` | `task:run` | 取消 |
| GET | `/api/runs/{run_id}/translate/progress` | `project:read` | 只读进度 |
| GET | `/api/runs/{run_id}/translate/batches/{batch_index}/{kind}` | `project:read` | 只读：批次中间文件下载 |

### artifacts（`backend/app/routers/artifacts.py`）

裸 `artifact_id`（不带 `project_id` 路径参数）的路由通过 `db.get_artifact` 反查所属项目——本批已把
项目归属校验接到这些路由上（不再是"只查能力、不查成员"），但下载仍是直接 `FileResponse`（无签名 URL/
流式代理),这部分留给批 4 复核，见移交说明。

| 方法 | 路径 | 能力 | 依据 |
|---|---|---|---|
| GET | `/api/projects/{project_id}/artifacts/{artifact_id}/download` | `project:read` | 见 projects 分组 |
| GET | `/api/artifacts/{artifact_id}/download` | `project:read` | 只读下载；`artifact_id` 反查 `project_id` |
| PATCH | `/api/artifacts/{artifact_id}` | `assets:curate` | 修改 artifact 的 label/role/origin/metadata；无已知前端调用点，按更严处理（可改变文件在系统中的用途分类） |
| GET | `/api/artifacts/{artifact_id}/translation-readiness` | `project:read` | 只读检查；`artifact_id` 反查 `project_id` |
| GET | `/api/artifacts/{artifact_id}/translation-targets` | `project:read` | 只读检查；`artifact_id` 反查 `project_id` |

## 能力分布统计

| 能力 | 路由数 |
|---|---|
| `task:run` | 41 |
| `project:read` | 37 |
| `assets:curate` | 20 |
| `project:manage` | 4 |
| `admin:*` | 2 |
| 豁免（EXEMPT） | 10 |
| **合计** | **114** |

## 拿不准、按更严归类的路由

- `PATCH /api/artifacts/{artifact_id}`：无已知前端调用点，语义是"重写一个文件在系统里的角色/元信息"，
  按 `assets:curate` 而非 `task:run` 处理。
- `POST /api/projects/{project_id}/glossary/import-preview`：本身只读（预览导入结果，不落库），但与
  紧邻的 `POST .../glossary/import` 是同一操作链路的两步，拆开授权没有实际业务意义，按 `assets:curate`
  统一处理。
- `POST /api/projects/{project_id}/glossary/extract`：AI 从项目资料提取术语候选，产物是待审核的
  `glossary_batches`/`glossary_candidates`（尚未写入已确认的 `glossary_terms`），但矩阵把"AI 补充"整体
  归入 `assets:curate`，按此处理而非 `task:run`。
  **裁决（A3 批 1+2，2026-07-15）**：`/glossary/extract`、`/glossary/batches/*`、`/glossary/candidates/*`
  保持 `assets:curate` 不变——矩阵的权威语义是三档（member）"不能主动修改术语库"，而确认候选会写入
  项目术语库，必须封锁。翻译向导第 5 步（术语候选，`StepFreqV2`）对无 `assets:curate` 的用户降级为
  **只读**：隐藏扫描/补译/确认/跳过/编辑等操作入口（候选数据仍可见），并且向导前进判定忽略
  pending 候选数（member 无法确认候选，不应被运营遗留的 pending 卡住；扫描任务进行中仍阻塞前进）。
- `POST /api/projects/{project_id}/improvements` 与 `POST /api/runs/{run_id}/improvement-review`：
  两者都是"QA 结果 → 项目改进建议队列"的写入动作，会被人工"应用到 Harness"，按项目资料维护
  (`assets:curate`) 处理而非任务操作；对应的 `GET`（列表）保持 `project:read`，因为同一数据本来就会随
  项目详情一起返回，收紧 GET 没有实际隔离效果。
- `GET /api/projects/{project_id}/harness`：矩阵原文把"项目资料/元信息/提示词维护"整行标为 member ❌，
  但 harness 数据已经随 `GET /api/projects/{id}`（`project:read`）一起返回，单独接口收紧到
  `assets:curate` 不会真正隔离数据，反而制造"两个入口权限不一致"的假象，所以保持 `project:read`；
  **写**入口 `PATCH` 保持 `assets:curate`，与矩阵一致。

## 与批 3、批 4 的边界

- 本批（批 1+2）已经把"发起/操作任务"“查看”类的 100+ 条路由全部纳入能力表并接上项目归属校验，
  能力表本身已经把批 3 要做的破坏性操作方向定好了（删项目 = `project:manage`，术语/归档手动
  维护 = `assets:curate`，项目资料维护 = `assets:curate`）——但目前 `member`/`ops` 打到这些路由时，
  能力检查已经会返回 403，这已经是实质性的封锁，批 3 不需要重新决定"该不该封"，只需要跑矩阵测试
  验证并补充这些路由自身的业务逻辑测试（例如"delete 时的级联清理""AI 补充报告"等与权限无关的行为）。
- 批 4（下载/artifact 直链复核）：本批已经把裸 `artifact_id` 路由接上了项目归属校验（防止跨项目下载
  枚举），但下载本身仍是同步 `FileResponse` 直出文件、无签名 URL/短时效 token/流式代理，批 4 如果要
  改造成签名 URL 或流式代理，可以在现有能力表基础上直接替换 handler 实现，不需要动
  `route_capabilities.py` 的表结构。

## 下载直链复核结论（A2 批 4）

已复核 `backend/app/download_urls.py`、artifact/delivery 下载 handler、`backend/app/main.py` 以及前端
`apiClient.ts`、`domain/artifacts.ts` 和各下载链接调用点：

- 后端生成的 artifact 与 delivery 下载地址全部以 `/api/` 开头，分别落到
  `/api/projects/{project_id}/artifacts/{artifact_id}/download` 和
  `/api/projects/{project_id}/delivery/{filename}`；前端自行拼接的回退地址也只使用这两类 `/api/`
  路径。保留的裸 artifact 地址 `/api/artifacts/{artifact_id}/download` 仍在集中网关内，并通过
  `db.get_artifact` 反查项目后执行成员校验。
- `main.py` 未挂载 `StaticFiles`，仓库内也没有把 `DATA_ROOT`、项目目录或 delivery 目录暴露为静态目录
  的代码；文件只能经已登记在 `CAPABILITY_BY_ROUTE` 的 `FileResponse` handler 返回。
- 权限回归已固定：非成员使用裸 `artifact_id` 下载返回 404；非成员按 delivery 文件名下载返回 404；
  未登录访问两类下载入口均返回 401。

结论：未发现绕过 `/api/` 集中认证/能力/项目成员网关的用户文件直链，无需修改下载实现。同步
`FileResponse` 在当前单实例 SQLite 部署中不是授权漏洞；若未来改为对象存储/CDN，再单独设计短时效签名
URL，不能直接公开持久对象地址。
