# 云端 Web 部署验收说明

> 目标：云端上传的文件必须能被同一个后端保存、读取、解析，并进入 AI 输入摘要；本地端默认行为不变。

## 必要配置

云端后端建议至少设置：

```powershell
$env:LWS_DEPLOYMENT_MODE = "cloud"
$env:LWS_DATA_ROOT = "D:\lws-data"
$env:LWS_CORS_ORIGINS = "https://your-web-domain.example.com"
```

要求：

- `LWS_DATA_ROOT` 必须是后端实例可读写的持久目录。
- 上传文件、SQLite 数据库、AI 产物、交付文件必须都在同一个持久目录下。
- 前端的 `/api` 必须稳定转发到同一个后端实例；不要上传打到 A 实例、分析打到 B 实例。

## 运维自检

1. 打开健康检查：

```text
GET /api/health
```

需要确认：

- `deployment_mode = cloud`
- `storage.data_root_writable = true`
- `storage.uploads_writable = true`
- `database.connected = true`
- `provider.provider_configured = true`

2. 上传可读性自检：

```text
POST /api/diagnostics/upload-readability
```

上传一个小的 `txt/md` 文件后，返回里必须有：

- `ok = true`
- `readable = true`
- `sha256`
- `preview`

再次查看 `/api/health`，应能看到 `latest_upload_readability`。

## 用户侧验收

- 项目 AI 分析 Step2 点击“查看 AI 输入摘要”，必须能看到文件名、解析状态、是否进入 AI。
- 如果文件无法解析，页面不能显示“AI 分析完成”，应提示具体原因。
- 翻译 Step7 点击“查看本次 AI 输入”，应能看到 prompt、workpack 行数、样例源文和术语命中。
- 公告 Step7 点击“查看 AI 输入”，应能看到公告分段、术语命中、prompt 摘要。

## 本地端不受影响

不设置 `LWS_DEPLOYMENT_MODE` 时默认是 `local`。本地终端和局域网模式继续使用原本的 `LWS_DATA_ROOT` 和 SQLite。
