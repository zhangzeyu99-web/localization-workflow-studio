# 配置说明

本文说明 Localization Workflow Studio 的本地配置、模型配置和运行边界。公开仓库只保存示例配置，真实数据和密钥必须放在仓库外的数据目录。

## 配置位置

默认数据目录：

```powershell
D:\codex\localization-workflow-studio-data
```

默认配置文件：

```powershell
D:\codex\localization-workflow-studio-data\settings.local.json
```

仓库内只保留示例：

```powershell
D:\codex\localization-workflow-studio\settings.example.json
```

`settings.local.json` 会在后端首次启动时自动创建。不要把它提交到 GitHub。

## 修改数据目录

默认使用 `D:\codex\localization-workflow-studio-data`。如需隔离测试数据或换盘，在启动后端前设置环境变量：

```powershell
$env:LWS_DATA_ROOT = "D:\codex\localization-workflow-studio-data-dev"
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

该目录会保存：

- `settings.local.json`
- `studio.sqlite3`
- 上传 workbook
- 生成 workbook
- run 日志
- 项目 profile / prompt / harness
- 内部 artifacts

## 推荐配置方式

本地调试可以通过网页右上角设置弹窗配置：

```text
http://127.0.0.1:5173
```

线上 Web 版不显示设置按钮，必须直接写入：

```text
<LWS_DATA_ROOT>/settings.local.json
```

本地可配置项：

- Provider：`GPT` / `GPT 中转站` / `Claude`
- 预设：`快速` / `平衡` / `深度` / `关键校对`
- API key

保存后，后端会写入仓库外的 `settings.local.json`。线上修改配置后建议重启后端。

## Provider 配置

内部 provider 值：

| 页面显示 | 配置值 | 协议 |
|---|---|---|
| GPT | `openai` | `responses` |
| GPT 中转站 | `openai-chat` | `chat-completions` |
| Claude | `anthropic` | `messages` |
| Test Fake | `test-fake` | `test-fake` |

当前正式 provider 为 GPT、GPT 中转站和 Claude。`test-fake` 只用于 CI、E2E 和无 key 回归测试。

## 预设模型

预设由后端固定映射，保存时会自动规范化 `model`、`reasoning_effort`、`base_url` 和 `protocol`。

| Provider | 预设 | model | reasoning_effort | max_output_tokens |
|---|---|---|---|---|
| GPT | `fast` | `gpt-5.4-mini` | `low` | 8192 |
| GPT | `balanced` | `gpt-5.5` | `medium` | 8192 |
| GPT | `deep` | `gpt-5.5-pro` | `high` | 16384 |
| Claude | `fast` | `claude-haiku-4-5-20251001` | `none` | 8192 |
| Claude | `balanced` | `claude-sonnet-4-6` | `adaptive` | 8192 |
| Claude | `deep` | `claude-opus-4-7` | `adaptive` | 16384 |

不建议手写 `model` 覆盖预设，因为保存配置时会按 provider 和 preset 自动重置。

## 示例配置

GPT 平衡档：

```json
{
  "provider": "openai",
  "preset": "balanced",
  "protocol": "responses",
  "base_url": "https://api.openai.com",
  "api_key": "sk-...",
  "model": "gpt-5.5",
  "reasoning_effort": "medium",
  "multimodal": {
    "images": true,
    "pdf": true,
    "video": false,
    "audio": false
  }
}
```

GPT 中转站平衡档：

```json
{
  "provider": "openai-chat",
  "preset": "balanced",
  "protocol": "chat-completions",
  "base_url": "https://aicode-api3.gz4399.com/api",
  "api_key": "<your-api-key>",
  "model": "gpt-5.5",
  "reasoning_effort": "medium",
  "multimodal": {
    "images": true,
    "pdf": true,
    "video": false,
    "audio": false
  }
}
```

Claude 深度思考档：

```json
{
  "provider": "anthropic",
  "preset": "deep",
  "protocol": "messages",
  "base_url": "https://api.anthropic.com",
  "api_key": "sk-ant-...",
  "model": "claude-opus-4-7",
  "reasoning_effort": "adaptive",
  "multimodal": {
    "images": true,
    "pdf": true,
    "video": false,
    "audio": false
  }
}
```

## API key 规则

- `GET /api/settings` 不会返回明文 key；已配置时只返回 `configured`。
- 网页里重新填写 key 才会替换现有 key。
- 提交空 key 或 `configured` 不会清空现有 key。
- 如需清空 key，手动编辑或删除 `settings.local.json`，然后重启后端。

## 长文本编排

长文本拆批、并发、RPM、TPM、单批 token、预算提醒和批次重试不再暴露给用户手调。后端会按 provider 预设自动选择保守参数：

- `fast`：更快响应，批次较小，并发保持 2。
- `balanced`：默认档，稳定优先，并发 2。
- `deep`：复杂内容和高质量审计，并发降为 1，单批上下文更大。

失败重跑时只应重跑失败批次或失败行，不应默认重跑整个项目。

## Test Fake ??

真实项目正式翻译禁止使用 `test-fake` 假装完成。

阻断规则：

- `provider = test-fake` 且项目名不是 `E2E ...`：正式翻译会进入 `needs_input`
- `provider = openai` 或 `anthropic` 但没有 API key：正式翻译会进入 `needs_input`

允许使用 test-fake 的场景：

- CI
- Playwright E2E
- 本地无 key 的链路回归
- 名称以 `E2E ` 开头的隔离测试项目

test-fake 输出不得进入真实项目交付验收。

## 多模态配置

`multimodal` 是能力探测和素材分析配置，不代表所有 provider 都一定会自动处理所有文件。

默认：

```json
{
  "images": true,
  "pdf": true,
  "video": false,
  "audio": false
}
```

当前原则：

- 支持的素材进入项目分析上下文。
- 不支持的素材归档并提示降级。
- 不阻断语言表、术语表、QA 主流程。

## 启动命令

后端：

```powershell
cd D:\codex\localization-workflow-studio
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

前端：

```powershell
cd D:\codex\localization-workflow-studio\frontend
npm run dev
```

打开：

```text
http://127.0.0.1:5173
```

## API 配置示例

查看当前公开配置：

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/settings"
```

切换到 GPT 平衡档：

```powershell
Invoke-RestMethod -Method Patch `
  -Uri "http://127.0.0.1:8000/api/settings" `
  -ContentType "application/json" `
  -Body '{"provider":"openai","preset":"balanced","api_key":"sk-..."}'
```

切换到 Claude 深度思考档：

```powershell
Invoke-RestMethod -Method Patch `
  -Uri "http://127.0.0.1:8000/api/settings" `
  -ContentType "application/json" `
  -Body '{"provider":"anthropic","preset":"deep","api_key":"sk-ant-..."}'
```

## 正式翻译验收条件

正式翻译不是只看 workbook 是否有英文列。必须同一个 run 同时具备：

- prompt snapshot / compiled style hint
- `translation_workpack.jsonl`
- `translation_manifest.json`
- provider `translation_response.jsonl`
- 回填前校验通过
- final workbook
- global QA + project harness QA
- hard error = 0

导入已有译文 workbook 后直接 QA 是合法流程，但它是 `QA run`，不能证明 Studio 完成了模型翻译。

## 常见问题

### 正式翻译按钮不可用

检查：

- Provider 是否为 `test-fake`
- GPT / Claude API key 是否为空
- 是否上传了语言表
- 目标语言是否为 EN

### 设置页显示 API key 为 configured

这是正常行为。后端不会把明文 key 返回给前端。

### 修改 settings.local.json 后没有生效

重启后端。运行中的 FastAPI 进程可能已经加载了旧配置。

### workflow 测试导入失败

不要从仓库根目录直接跑 `python -m pytest -q workflow\localization`。进入 workflow 目录后执行：

```powershell
Push-Location workflow\localization
python -m pytest -q
Pop-Location
```

### 真实数据混入公开仓库

检查 `.gitignore` 是否仍排除：

- `settings.local.json`
- `*.sqlite`
- `*.db`
- `uploads/`
- `runs/`
- `projects/`
- `outputs/`
- `*_translated.xlsx`
- `*_final.xlsx`
- `*_output.xlsx`

提交前运行：

```powershell
git status --short
```
