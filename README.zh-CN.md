# Localization Workflow Studio

面向游戏本地化团队的本地优先工作台：把 Excel 语言表、AI 辅助翻译、术语库、规则 QA、译文归档和最终交付物收进一条可审计流程。

## 入口

- 公开 Demo：https://zhangzeyu99-web.github.io/localization-workflow-studio/
- 快速上手：[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)
- 公开案例：[docs/SHOWCASE.md](docs/SHOWCASE.md)
- 合成样例 workbook：[examples/synthetic-language.xlsx](examples/synthetic-language.xlsx)
- 英文 README：[README.md](README.md)

GitHub Pages Demo 是只读静态页面，不上传文件、不调用模型、不保存数据，也不包含真实客户素材。完整流程需要本地 FastAPI 后端。

## 适合谁

- 需要 Excel 交付门槛的游戏本地化 PM / 制作人。
- 需要术语、占位符、标签、换行和 UI 长度检查的译者和 LQA。
- 用 GPT 或 Claude 辅助翻译，但仍需要人工审查和可追溯交付物的小团队。
- 想参考本地优先 AI 工作流设计的开发者。

## 核心能力

- 录入项目资料、风格规则和术语库。
- 从 Excel 语言表生成带稳定 ID 的 workpack。
- 按批次调用正式 provider 做 AI 辅助翻译。
- 阻止 mock 或缺失 API key 的结果被当成真实交付。
- 检查占位符、富文本标签、换行、术语一致性、可读性和 UI 长度。
- QA 通过后写入译文归档并生成最终交付 workbook。

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

真实配置和运行数据应放在仓库外：

```text
D:\codex\localization-workflow-studio-data
```

不要提交：

- 真实项目 workbook
- 客户源文
- API key
- SQLite
- run 日志
- workpack
- QA 报告
- 私有项目最终交付物

## 质量门槛

正式交付必须满足：

1. 有 prompt snapshot、project harness snapshot、glossary snapshot。
2. workpack 记录 ID、源文、文本类型、占位符、标签、换行形态、术语命中、UI 长度和输入指纹。
3. 模型返回遵守 JSONL 行协议，每行只包含 `id` 和 `translation`。
4. 回填前校验 ID、顺序、占位符、标签、换行和输入指纹。
5. 最终 workbook 通过规则 QA 和项目规则 QA，hard issue 为 0。
6. QA 通过后才写入译文归档并生成最终交付物。

导入已有译文 workbook 做 QA 是支持的，但它只能证明 Studio 做过校对，不代表 Studio 做过原始翻译。
