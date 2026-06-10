# 稳定状态测试列表

目标：确认工作台脱离 Codex/Agent 后，仍能只靠本地后端、内置 workflow 和已配置 API provider 完成核心流程。

## 运行方式

```powershell
python scripts\stability_check.py --base-url http://127.0.0.1:5174
```

- 默认新建 `STABILITY-YYYYMMDDHHMMSS` 临时项目。
- 测试完成后自动删除临时项目。
- 报告写入 `.tmp/stability/<项目名>/stability-report.json`。
- 只调用工作台后端与配置的 API provider；不调用 Codex 模型能力，不使用 Google 或浏览器机翻。

## 必测项

1. 后端健康检查：`/api/health`。
2. Provider 配置检查：真实 provider 必须有 API key。
3. 创建项目。
4. Step 1 上传项目资料。
5. Step 2 AI 分析：通过后端 provider 生成项目 profile / prompt。
6. Step 3 上传术语表、预览、导入、导出。
7. Step 4 上传语言表、readiness 检查。
8. 正式翻译 run：后台拆批、API 翻译、本地回填、QA 终态。
9. 直接 QA run：上传已有译文 workbook 后跑 QA。
10. 译文归档：导入归档，导出 XLSX / CSV。
11. 快速任务：创建 quick translation run，后台翻译，QA 终态。
12. 公告任务：上传源文、创建任务、识别约束、提取公告术语、译文反查、prepare 中转表与 workpack。

## 通过标准

- 所有步骤返回 `ok=true`。
- 上传、分析、导入等步骤不得出现 `Failed to fetch`。
- 翻译任务必须完成全部行；若 QA 未通过，也必须有明确 QA 结果和问题报告，不允许卡死。
- 快速任务页面不得展示内部批处理日志，例如 `source_rows=...`、`rows=...`、`attempt=...`、`running: C:\...`。
- 临时项目必须自动删除，除非显式加 `--keep-project`。
