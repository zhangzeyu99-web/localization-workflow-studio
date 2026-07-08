# 稳定性验收清单

目标：确认工作台脱离 Codex/Agent 后，仍能只靠本地后端、内置 workflow 和已配置 API provider 完成核心流程。

## 本地 / 局域网

```powershell
python scripts\deployment_check.py --base-url http://127.0.0.1:5174 --expect-version (Get-Content VERSION)
python scripts\stability_check.py --base-url http://127.0.0.1:5174
```

## Linux / 线上

```bash
python3.11 check.py --base-url https://ai-lwstudio.example.com --require-cloud --require-provider --expect-version $(cat VERSION)
python3.11 scripts/stability_check.py --base-url https://ai-lwstudio.example.com
```

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

## 失败即阻断

- 页面能打开但 `/api/version` 404。
- `/api/health` 不是 `cloud`。
- 上传自检失败。
- 数据目录不可写。
- provider 未配置但尝试跑正式 AI 翻译。
- 下载最终交付文件返回 Not Found。
- 测试项目删除失败。
