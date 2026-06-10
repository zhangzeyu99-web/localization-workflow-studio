# Localization Workflow Studio

面向游戏本地化团队的本地优先工作台，用于处理 Excel 语言表、AI 辅助翻译、术语 QA、交付检查和最终 workbook 产物。

[English README](README.md)

## 快速入口

- 公开 Demo: https://zhangzeyu99-web.github.io/localization-workflow-studio/
- 工作流指南: [docs/guides/ai-game-localization-workflow.html](docs/guides/ai-game-localization-workflow.html)
- Excel QA 指南: [docs/guides/excel-translation-qa.html](docs/guides/excel-translation-qa.html)
- 快速上手: [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)
- 公开案例: [docs/SHOWCASE.md](docs/SHOWCASE.md)
- 合成示例 workbook: [examples/synthetic-language.xlsx](examples/synthetic-language.xlsx)
- 反馈讨论: [GitHub Discussions #29](https://github.com/zhangzeyu99-web/localization-workflow-studio/discussions/29)
- Help wanted: [真实 workbook 格式和 QA gates 反馈](https://github.com/zhangzeyu99-web/localization-workflow-studio/issues/30)

GitHub Pages Demo 是只读静态页面，不上传文件、不调用模型、不保存数据，也不包含真实客户素材。完整工作流需要在本地启动 FastAPI 后端。

## 适合谁

- 仍然用 Excel 语言表交付的游戏本地化 PM、制作人或运营同学。
- 需要检查术语、占位符、富文本标签、换行和 UI 长度的译者或 LQA。
- 使用 GPT/Claude 辅助翻译，但仍需要人工审查和可追溯交付物的小团队。
- 想参考本地优先 AI 工作流、QA gates 和交付归档设计的开发者。

## 核心能力

- 从项目资料、风格规则、术语表和语言表建立项目工作区。
- 将 Excel 语言表转换为带稳定 ID 的 workpack。
- 为 AI 辅助翻译生成带术语、占位符、标签和 UI 长度提示的 prompt。
- 阻止 mock 输出或缺失 provider key 的结果进入真实交付链路。
- 检查占位符、富文本标签、换行、术语一致性、可读性和 UI 长度。
- 支持人工修复后再生成最终交付 workbook。
- 将运行数据、SQLite、日志、API key 和真实 workbook 保持在公开仓库之外。

## 本地启动

```powershell
git clone https://github.com/zhangzeyu99-web/localization-workflow-studio.git
cd localization-workflow-studio

python -m pip install -r backend\requirements.txt

cd frontend
npm ci
npm run build
```

启动后端：

```powershell
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

启动前端：

```powershell
cd frontend
npm run dev
```

打开：

```text
http://127.0.0.1:5173
```

## 数据边界

真实配置和运行数据应该放在仓库外，例如：

```text
D:\codex\localization-workflow-studio-data
```

不要提交：

- 真实项目 workbook
- 客户源文
- API key
- SQLite 数据库
- run 日志
- 真实交付产物

## 为什么值得 Star

如果你关注这些方向，可以 star 这个仓库作为参考：

- 本地优先 AI 工作流
- 游戏本地化 QA 自动化
- Excel 交付链路
- provider 安全配置
- 可复现的翻译审查 gates
- React + FastAPI 工作台实现
