# 多人使用改造计划（2026-07-08）

> 目标：小团队（2-10 人）共用一个部署，各自同时跑翻译/QA/公告任务，互不卡死、互不踩配置。
> 边界：不做账号/权限/登录体系；不改 SQLite 技术栈；保持单实例单 uvicorn worker；不改翻译/QA/交付业务语义和 API 输出契约。
> 执行模式：fable5 循环（主线程架构决策 + Sonnet 5 子 agent 执行），隔离 worktree，每批验证合并。

---

## 0. 事实基线（2026-07-08 探查，两组独立探查互相印证）

- 任务锁：`backend/app/jobs.py` 全产品一把锁——进程内 `_ACTIVE_JOB` + SQLite `job_leases` 单行（`_LEASE_NAME="long_text"` 硬编码）。翻译（`run:{run_id}`）、多语言队列（`multilingual:*`）、公告（`announcement:*`）、model-fix（`model-fix:{run_id}`）全部互斥；第二人得 409 "another long-text AI job is active"（runs.py:140/161、qa.py:95/163、announcement.py:255/271 共 6 处；多语言队列走 `active_conflict` 返回体不抛 409）。
- `job_leases` 表 `name TEXT PRIMARY KEY`（db.py:242-250），结构天然支持多行 lease，业务只用过一个名字。无心跳、无 TTL，仅启动时 `mark_running_job_leases_interrupted` 清残留（translation.py:627+）。
- 已知不一致：`cancel_translation_run`（translation.py:590）用 `run_id` 调 `cancel_job_lease`，而锁内 job_id 是 `run:{run_id}`，WHERE 可能匹配不到；取消实际靠内存 cancel_event + 文件哨兵兜底生效。
- SQLite：每操作新开连接、无 WAL（默认 rollback journal，写加库级锁）、`busy_timeout=30000`（db.py:80-91）。"不炸"的前提是全局单任务锁保证同时只有一个密集写者。
- N-5 竞态：`metadata={**db.get_run(...).get("metadata", {}), ...}` 整体替换模式散布 ~15 处（translation_orchestrator.py:110-112/285-299、translation.py 多处、routers/runs.py:143/159、routers/qa.py:97-162 四段、multilingual.py:105-110/167-168、announcement.py:256/263-265）。单锁下自然串行，放开并发即 last-write-wins。
- 限流：`_AsyncTokenRateLimiter`（translation_batches.py:268-298）每次编排调用新建（orchestrator.py:304-307），滑动 60s 窗口约束 RPM/TPM。两 run 并行时各自独立、互不知晓，同 provider 预算会叠加超发。限流全局正确性完全依赖"同时只有一个 run"。
- 配置：`settings.local.json` 全局单份（config.py:14）。翻译编排在任务开始时快照传入，但 model-fix/glossary/QA/semantic_qa/announcement_ai 等路径执行中途各自 `load_settings()`——A 改 provider 会影响 B 运行中的任务。云端模式 PATCH /api/settings 已 403。
- 目录：project/run 目录天然按 id 隔离；`batch_manifest.json` 用 asyncio.Lock 串行（仅单事件循环内有效，跨 run 无效但文件本身按 run 隔离，无冲突）；同项目 `project_harness.json`、`improvement_suggestions.json` 是读-改-写整文件，同项目并发编辑可互踩。
- 身份：无任何 user/session/owner 概念；`events` 表只有 run_id/level/message/created_at，是 run 级过程日志，不是操作审计。
- 部署：`start-lws.sh` `--workers 1` 写死；CLOUD_DEPLOYMENT.md:60-62 记录了单实例单任务约束（本计划落地后需更新该段）。
- 前端：轮询接口按 id 取数，无用户隔离（纯客户端显示隔离）；`create_run` 已有同项目同 kind 互斥守卫（runs.py:49-55）。

## 1. 目标并发模型

一句话：**锁从"全产品一把"变成"每项目一把"，加一个全局并发上限；限流和配置从"假设只有一个任务"变成"并发任务共享预算、各自持有配置快照"。**

```text
用户A(项目X 翻译) ─┐
用户B(项目Y 翻译) ─┼→ 项目级 lease long_text:{project_id}（同项目仍互斥）
用户C(项目X QA)  ─┘      ↓ 通过
                    全局并发上限 max_concurrent_ai_jobs（默认 2，可配）
                          ↓ 通过
                    并行 run（批次编排逻辑不变）
                          ↓
                    进程级共享限流器（按 provider 分桶，线程安全）
                          ↓
                    SQLite（WAL + merge_run_metadata 原子合并）
```

设计决策：

- **同项目互斥保留**：项目内串行是大量现有假设的地基（断点续跑、manifest、harness 文件读改写、`create_run` 守卫），不动。两人操作同一项目时后到者仍被拒，提示改为"该项目正在执行任务"。
- **全局上限而非无限并发**：provider 预算、内存、SQLite 写压都需要上界；默认 2、上限 4，settings 可调。
- **不做鉴权**：操作留痕用可选的浏览器本地昵称（请求头 `X-Operator`），只记录不校验。

## 2. 阶段与批次

### 阶段 M1：并发安全地基（先行，独立可合并）

- 批 1：SQLite WAL。`db.connect()` 增加 `PRAGMA journal_mode=WAL` + `synchronous=NORMAL`；确认 WAL 文件在 DATA_ROOT 可写；验证现有全量测试无回归。
- 批 2：N-5 修复。新增 `db.merge_run_metadata(run_id, patch)`（单连接事务内 SELECT+merge+UPDATE），替换全部 ~15 处 `{**get_run(...), ...}` 调用点；新增并发合并回归测试（两线程同时 patch 不同 key，断言两个 key 都在）。
- 批 3：顺手修已知锁不一致——`cancel_translation_run` 的 `cancel_job_lease` job_id 参数改为 `run:{run_id}` 格式（或按 lease 名取消），加回归测试。

### 阶段 M2：锁粒度演进

- 批 1：lease 名参数化。`jobs.py` 的 `_LEASE_NAME` 改为 `lease_name_for_project(project_id)` → `long_text:{project_id}`；`_ACTIVE_JOB` 单槽改为 `dict[lease_name, BackgroundJob]`；`active_job_id()` 改为 `active_jobs()`（返回全部活跃任务）；调用点（runs/qa/announcement/multilingual 5 个入口）传 project_id。
- 批 2：全局并发上限。settings 新增 `max_concurrent_ai_jobs`（默认 2，夹在 1-4）；`start_singleton_job` 在项目锁检查后加全局计数检查；两种拒绝返回不同结构：`{"reason": "project_busy", "active_job": ...}` 与 `{"reason": "capacity", "active_count": N}`。
- 批 3：恢复与取消适配。`reconcile_interrupted_background_jobs` 按 `long_text:%` 前缀清理全部残留 lease；`mark_running_job_leases_interrupted` 同步适配；409 文案区分两种原因（前端 apiClient 正则同步更新）。
- 批 4：新增 `GET /api/system/active-jobs`：返回活跃任务列表（lease 名、job 类型、项目名、开始时间），供前端活跃任务面板和排队提示使用。
- 回归测试：两项目并行翻译（test-fake）都完成且互不影响；同项目第二个任务被拒且 reason=project_busy；上限占满后 reason=capacity；重启后多 lease 全部恢复清理。

### 阶段 M3：资源共享正确性

- 批 1：共享限流器。`translation_batches.py` 新增进程级 `SharedRateLimiter`（threading.Lock 实现——各 run 的 asyncio 循环在不同线程，asyncio.Lock 跨不了；按 provider+api_key 哈希分桶）；编排层改为从共享注册表取 limiter，RPM/TPM 预算全局生效；单 run 场景行为与现状等价（测试断言）。
- 批 2：settings 快照。所有 AI 路径改为任务启动时 `load_settings()` 一次并全程传递：排查 model-fix（qa_model_fixes.py:25）、glossary_ai.py:124、semantic_qa.py:23、announcement_ai.py:175、project_analysis.py:452、qa.py:923 等中途 load 点；改动原则是把 settings 作为参数下传，不新建全局缓存。
- 批 3：同项目共享文件防护。`project_harness.json`、`improvement_suggestions.json` 的读-改-写加文件锁（同项目已互斥，主要防 API 线程编辑 vs 后台任务写的窗口）；低成本用 `threading.Lock` 按 project_id 分桶即可。
- 回归测试：两 run 并行时合计请求速率不超 RPM 配置（用 test-fake 计数断言）；任务运行中 PATCH settings 不影响该任务已快照的 provider。

### 阶段 M4：前端呈现与留痕（依赖前端优化计划 F2 拆分完成）

- 活跃任务面板：头部显示当前活跃任务（来自 `GET /api/system/active-jobs`），含项目名、任务类型、开始时间；409/排队提示引导查看面板。
- 排队体验：`project_busy`/`capacity` 两种拒绝给不同提示；capacity 场景提示"当前 N 个任务在跑，稍后重试"。
- 可选操作人标记：设置里填昵称（localStorage），请求头 `X-Operator` 带上；后端 `add_event` 和关键操作（创建项目、发起任务、交付）记录进 events/metadata；不做校验。
- e2e：新增并发场景用例（两项目并行发起、面板显示、同项目拒绝提示）。

### 阶段 M5：部署收尾

- CLOUD_DEPLOYMENT.md 更新：替换"单实例单任务"约束段为新并发模型说明（项目级锁 + 全局上限 + 共享限流），保留"单实例单 worker、不共享 SQLite 给多 worker"的约束。
- STABILITY_TEST_LIST.md 增加多人并发测试项（并行翻译、上限拒绝、重启恢复多 lease）。
- 新增 `scripts/concurrency_smoke.py`：起两个 test-fake 翻译并行跑，校验都完成、限流总量、无 database is locked。
- Tier D 验收 + 版本联动（MINOR：用户可见的并发能力变化）。

## 3. 验证分层

- 每批：Tier A + 聚焦测试（jobs/orchestrator/multilingual/delivery 相关）。
- 每阶段末：Tier C 全量（pytest + e2e）。
- M2、M5 末：Tier D（deployment_check + stability_check + concurrency_smoke）。
- 失败两次即停，登记 blocker（fable5 规则）。

## 4. 完成标准

- [ ] 两个用户在不同项目同时发起翻译，各自正常完成、交付、归档（e2e/冒烟证据）。
- [ ] 同项目并发仍被拒且提示明确说"该项目正在执行任务"。
- [ ] 全局上限生效且提示区分"项目忙"与"容量满"。
- [ ] 并行任务合计请求速率不超全局 RPM/TPM 配置。
- [ ] 任务运行中他人改 settings 不影响运行中任务。
- [ ] 重启后所有残留 lease 正确清理、任务标记 needs_input。
- [ ] 全量 pytest + e2e 绿；concurrency_smoke 通过；CLOUD_DEPLOYMENT/STABILITY_TEST_LIST 更新。

## 5. 风险与对策

- SQLite 写竞争放大：WAL + busy_timeout 30s + 全局上限默认 2 控制写压；冒烟脚本专门盯 `database is locked`；出现即降默认上限并记录。
- 共享限流让单任务变慢：预算总量不变、并发分享是预期行为；文档写明，preset 默认值不改。
- 锁粒度改动破坏断点续跑/恢复：M2 批 3 专门覆盖恢复路径回归测试；恢复逻辑改动是本计划最高风险点，需要 Architect 检查点。
- 前端 apiClient 的 409 正则（apiClient.ts:13）依赖旧文案：M2 批 3 后端改文案与前端正则同批更新。
- 与前端优化计划的并行冲突：M1-M3 纯后端，可与前端 F1 并行；M4 必须等前端 F2 拆分完成，避免在 2500 行 main.tsx 上加面板。
