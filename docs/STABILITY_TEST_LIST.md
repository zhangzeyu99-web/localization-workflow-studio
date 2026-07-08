# 稳定性验收清单

目标：确认工作台脱离 Codex/Agent 后，仍能只靠本地后端、内置 workflow 和已配置 API provider 完成核心流程。

## 本地 / 局域网

```powershell
python scripts\deployment_check.py --base-url http://127.0.0.1:5174 --expect-version (Get-Content VERSION)
python scripts\stability_check.py --base-url http://127.0.0.1:5174
python scripts\concurrency_smoke.py --base-url http://127.0.0.1:5174
```

## Linux / 线上

```bash
python3.11 check.py --base-url https://ai-lwstudio.example.com --require-cloud --require-provider --expect-version $(cat VERSION)
python3.11 scripts/stability_check.py --base-url https://ai-lwstudio.example.com
python3.11 scripts/concurrency_smoke.py --base-url https://ai-lwstudio.example.com
```

多人并发场景务必在隔离实例（临时数据目录、独立端口）上跑，不要对生产库跑。

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

## 多人并发测试项（M2-M5）

15. 两个不同项目同时发起翻译 run，各自基于独立的 `long_text:{project_id}` lease 并行跑完、都交付成功，互不阻塞、互不踩坏对方的 metadata（`scripts/concurrency_smoke.py` 覆盖）。
16. 同一项目内第二个任务（翻译/QA/公告/模型修复）在第一个任务运行期间发起，被拒绝且提示"该项目正在执行任务（{任务描述}），请等它完成或先取消"（`project_busy`）。
17. 工作台整体活跃任务数达到 `max_concurrent_ai_jobs`（默认 2）上限时，新任务被拒绝且提示"工作台已有 {N} 个任务在跑（上限 {M}），请稍后再试"（`capacity`）；上限释放后新任务能正常起跑。
18. 前端头部活跃任务面板能显示 `GET /api/system/active-jobs` 返回的全部活跃任务（项目名、任务类型、开始时间），且 409 排队提示能区分"项目忙"与"容量满"两种场景。
19. 后端重启后，重启前所有残留的 `long_text:*` lease 被统一清理，对应的 run 标记为 `needs_input`，不会有任务因残留 lease 被永久卡住。
20. 一个任务运行期间，另一处修改全局 `settings.local.json`（provider/preset 等）不影响已经在跑的任务——已启动任务使用启动时的 settings 快照，运行结果不受运行中途配置变更影响。
21. 项目存在活跃任务时尝试删除该项目，被拒绝且提示"该项目正在执行任务（{任务描述}），请先取消或等待任务完成再删除"；任务结束后删除能正常成功。

## 失败即阻断

- 页面能打开但 `/api/version` 404。
- `/api/health` 不是 `cloud`。
- 上传自检失败。
- 数据目录不可写。
- provider 未配置但尝试跑正式 AI 翻译。
- 下载最终交付文件返回 Not Found。
- 测试项目删除失败。
