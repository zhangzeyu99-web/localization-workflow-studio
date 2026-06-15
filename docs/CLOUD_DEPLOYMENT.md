# 云端 / Linux 部署验收说明

## 结论

线上部署必须满足五件事：同一份最新代码、可写的数据目录、已构建的前端、单实例后端、可验证的健康检查。不要直接用 Vite dev server 当线上环境。

## 推荐目录

```text
/data/web/lwstudio
/data/web/lwstudio/lws-data
```

`/data/web/lwstudio` 放代码和前端构建产物；`/data/web/lwstudio/lws-data` 放私有运行数据，不提交 Git，不对公网静态暴露。

## 方式 A：用 GitHub 源码部署

```bash
cd /data/web
git clone https://github.com/zhangzeyu99-web/localization-workflow-studio.git lwstudio
cd /data/web/lwstudio

python3.11 -m pip install -r backend/requirements.txt
python3.11 -m pip install -r workflow/glossary/requirements.txt
python3.11 -m pip install -r workflow/localization/requirements.txt

cd frontend
npm install
npm run build
cd ..
```

注意：GitHub 源码不跟踪 `frontend/dist`，所以源码部署必须执行 `npm run build`。

## 方式 B：用发布包部署

发布包已经包含后端、前端源码、workflow 副本、Linux 启动脚本和安装说明；如果包内已有 `frontend/dist`，仍建议部署后重新执行一次 `npm run build`，避免线上静态文件版本滞后。

```bash
cd /data/web
unzip 本地化工作台-v1.0.1-YYYYMMDD.zip
mv localization-workflow-studio-v1.0.1-YYYYMMDD lwstudio
cd /data/web/lwstudio
```

## 后端启动

```bash
cd /data/web/lwstudio
chmod +x ./start-lws.sh
APP_HOME=/data/web/lwstudio \
LWS_DATA_ROOT=/data/web/lwstudio/lws-data \
LWS_DEPLOYMENT_MODE=cloud \
LWS_MAX_UPLOAD_MB=1024 \
./start-lws.sh
```

默认监听：`127.0.0.1:8082`。

第一版线上固定单实例、单 worker。不要用多个 uvicorn worker 直接共享 SQLite。

## Nginx 参考配置

```nginx
server {
  listen 443 ssl http2;
  server_name ai-lwstudio.example.com;

  root /data/web/lwstudio/frontend/dist;
  index index.html;
  client_max_body_size 1024m;

  location / {
    try_files $uri $uri/ /index.html;
  }

  location /api/ {
    proxy_pass http://127.0.0.1:8082;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
  }
}
```

## Provider 配置

线上 Web 版不在前端显示 API 设置入口。Provider、Base URL、API key 直接写入私有数据目录：

```bash
cat > /data/web/lwstudio/lws-data/settings.local.json <<'JSON'
{
  "provider": "openai-chat",
  "preset": "balanced",
  "protocol": "chat-completions",
  "base_url": "https://aicode-api3.gz4399.com/api",
  "api_key": "<your-api-key>",
  "model": "gpt-5.5",
  "reasoning_effort": "medium"
}
JSON
```

不要把 `settings.local.json` 放进代码目录、Git 仓库或前端静态目录。

## 必须设置的环境变量

```bash
export LWS_DEPLOYMENT_MODE=cloud
export LWS_DATA_ROOT=/data/web/lwstudio/lws-data
export LWS_MAX_UPLOAD_MB=1024
```

可选：

```bash
export LWS_CORS_ORIGINS=https://ai-lwstudio.example.com
export LWS_GIT_SHA=$(git rev-parse --short=12 HEAD)
```

## 上线前自检

```bash
python3.11 check.py --base-url https://ai-lwstudio.example.com --require-cloud --require-provider --expect-version $(cat VERSION)
```

必须看到：

- `/api/version` 返回当前版本和提交号，且版本号必须和部署包 `VERSION` 一致。
- 前端右下角显示同一版本号。
- `/api/health` 返回 `deployment_mode=cloud`。
- `data_root_writable=true`。
- `uploads_writable=true`。
- `database.connected=true`。
- `provider_configured=true`。
- 上传自检能返回 `sha256` 和 `preview`。

完整业务冒烟测试：

```bash
python3.11 scripts/stability_check.py --base-url https://ai-lwstudio.example.com
```

它会临时创建测试项目，跑项目资料上传、AI 分析、术语导入、翻译、QA、归档、公告准备等关键路径，默认结束后删除测试项目。

## 常见失败判断

| 现象 | 判断 | 处理 |
|---|---|---|
| `/api/version` 404 | 后端不是最新代码 | 重启后端，确认部署目录和启动命令 |
| `/api/health` 是 local | 没设 `LWS_DEPLOYMENT_MODE=cloud` | 补环境变量后重启 |
| 上传 413 | Nginx 或后端上传上限不一致 | 同时设置 `client_max_body_size` 和 `LWS_MAX_UPLOAD_MB` |
| 页面能开但上传/分析失败 | 前端和后端不是同一版本，或 `/api/` 反代错 | 看右下角版本号、`/api/version` 和浏览器 network |
| 下载 Not Found | 数据目录变了或旧 artifact 文件不存在 | 确认 `LWS_DATA_ROOT` 持久且未被覆盖 |
| 多人同时跑任务混乱 | 多 worker/多实例共用 SQLite | 第一版固定单 worker 单实例 |

## 不要做

- 不要把 `lws-data` 放进 Git。
- 不要把 `settings.local.json`、API key、真实项目文件放进发布包。
- 不要在云端前端暴露 API 设置按钮；线上只通过数据目录配置文件管理密钥。
- 不要用 `npm run dev` 做线上服务。
- 不要开多个 uvicorn worker 直接共享 SQLite。
- 不要让 Nginx 直接暴露 `lws-data`。
