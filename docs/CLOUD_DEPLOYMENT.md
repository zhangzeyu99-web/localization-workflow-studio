# 云端单节点部署

## 结论

v1.7.1 同时交付 `有账号-v1.7.1.zip` 与 `无账号-v1.7.1.zip`。有账号包是默认使用 `cloud/required` 的 universal 制品，保留登录、注册、角色和项目成员权限；无账号包的 manifest、Linux 启动脚本、systemd 服务和环境模板都锁定为内网 `cloud/off`，只适用于已有网络访问控制的可信公司内网，禁止直接暴露到公网。

线上采用“同域 Nginx + 单个 FastAPI worker + 独立持久数据目录”。前端只使用包内已验证的 Vite 构建产物，不运行开发服务器；SQLite、上传文件、任务产物和 `settings.local.json` 都放在版本目录之外。部署模板位于 `deploy/`。

## 目录契约

```text
/srv/lwstudio/
├── releases/
│   ├── 20260714-af3ab0b/
│   └── 20260716-<git-sha>/
├── current -> /srv/lwstudio/releases/20260716-<git-sha>
└── data/
    ├── settings.local.json
    ├── studio.sqlite3
    ├── projects/
    ├── uploads/
    ├── runs/
    └── artifacts/
```

- `releases/`：每次发布一个只读版本目录，不在原目录上覆盖升级。
- `current`：systemd 和 Nginx 唯一引用的软链，发布和回滚只切换该软链。
- `data/`：跨版本持久目录，禁止放进任一 release，禁止交给 Nginx 静态暴露。

## 首次安装

以下命令以 Debian/Ubuntu 为例；发布包已解压到 `/srv/lwstudio/releases/<release-id>`。

```bash
sudo useradd --system --home /srv/lwstudio --shell /usr/sbin/nologin lwstudio
sudo install -d -o lwstudio -g lwstudio -m 0750 /srv/lwstudio/releases /srv/lwstudio/data
sudo install -d -o root -g lwstudio -m 0750 /etc/lwstudio

cd /srv/lwstudio/releases/<release-id>
python3.11 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/pip install -r workflow/glossary/requirements.txt
.venv/bin/pip install -r workflow/localization/requirements.txt
test -f frontend/dist/index.html

sudo chown -R root:root /srv/lwstudio/releases/<release-id>
sudo ln -sfn /srv/lwstudio/releases/<release-id> /srv/lwstudio/current
# 两个 v1.7.1 包都使用各自包内的 deploy/lws.env.example。
sudo cp deploy/lws.env.example /etc/lwstudio/lws.env
sudo chown root:lwstudio /etc/lwstudio/lws.env
sudo chmod 0640 /etc/lwstudio/lws.env
```

如果部署有账号的 universal 制品，则改用 `deploy/profiles/cloud-required.env.example`，并按下文配置初始管理员。不要把两种模板混用。

发布包必须携带已经在构建环境完成验证的 `frontend/dist`。服务器不得重新执行 `npm ci` 或 `npm run build`，否则现场生成的前端可能与包内后端版本不一致。

编辑 `/etc/lwstudio/lws.env`，把 `LWS_GIT_SHA` 设置为发布包 `PACKAGE_MANIFEST.json` 中的 `git_sha`，不要手工猜测或填写工作区 HEAD。`LWS_DATA_ROOT` 必须保留为版本目录之外的绝对路径；cloud 模式下缺失或使用相对路径会在启动时直接失败。

安装服务和反向代理模板：

```bash
sudo cp /srv/lwstudio/current/deploy/lws.service /etc/systemd/system/lws.service
sudo cp /srv/lwstudio/current/deploy/nginx.conf /etc/nginx/sites-available/lwstudio.conf
sudo ln -sfn /etc/nginx/sites-available/lwstudio.conf /etc/nginx/sites-enabled/lwstudio.conf
sudo systemctl daemon-reload
sudo systemctl enable --now lws.service
sudo nginx -t
sudo systemctl reload nginx
```

上线前把 `deploy/nginx.conf` 的 `server_name` 和证书配置改成真实域名。模板只把 FastAPI 暴露在 `127.0.0.1:8082`，不得改成公网监听，也不得使用 `npm run dev` 或把 5173 端口接入线上流量。

## 服务端 API 配置

线上 provider 配置只写入 `/srv/lwstudio/data/settings.local.json`。不要把真实 key 写进 `lws.env`、发布包、Git、前端环境变量或浏览器存储。

```bash
sudo -u lwstudio tee /srv/lwstudio/data/settings.local.json >/dev/null <<'JSON'
{
  "provider": "openai-chat",
  "preset": "balanced",
  "protocol": "chat-completions",
  "base_url": "https://your-provider.example.com/api",
  "api_key": "replace-on-server",
  "model": "replace-on-server",
  "reasoning_effort": "medium"
}
JSON
sudo chmod 0600 /srv/lwstudio/data/settings.local.json
sudo systemctl restart lws.service
```

cloud 模式禁止从网页修改 provider 设置。后续变更仍由运维编辑外置 `settings.local.json` 并重启服务；文件权限保持 `0600`。

## 缓存、上传与边缘层

`deploy/nginx.conf` 的合同如下：

- `/api/*`：禁止代理缓存，响应强制 `Cache-Control: no-store`。
- `index.html` 和前端路由回退：`Cache-Control: no-cache`，每次向源站校验。
- `/assets/*`：文件名带内容哈希，允许一年 immutable 缓存。
- 上传上限：Nginx `1g`，应用环境 `LWS_MAX_UPLOAD_MB=1024`。
- AI 长任务：代理读写超时均为 600 秒。

如果域名前还有 CDN、WAF 或其他边缘代理，必须配置为：不缓存 `/api/*`；不覆盖源站的 `no-store`/`no-cache`；发布后主动刷新 `/` 和 `/index.html`。不能只看源站 Nginx 配置，必须从公网域名检查最终响应头。

`cloud/required` 由应用自身强制登录并按账号、角色和项目成员关系鉴权。`cloud/off` 没有应用层账号边界，必须由公司内网、VPN、网关白名单等外层能力限制访问。两个 cloud profile 都要求用 `X-Operator` 昵称记录 AI 任务操作人；昵称只用于留痕，不是身份认证。

## 账号与认证

受支持的运行配置矩阵：

```text
local + off（默认）       → 本地免登录生产配置
cloud + required（默认） → 线上强制登录生产配置
cloud + off              → 可信内网无账号生产配置
local + required         → 仅用于测试或开发
```

`LWS_DEPLOYMENT_MODE` 与 `LWS_AUTH_MODE` 必须组成合法 profile；其它非法值会让后端启动失败，不会静默降级。直接从源码或 universal 制品启动 cloud 时，未指定 `LWS_AUTH_MODE` 仍默认为 `required`；专用无账号制品则在启动脚本、systemd 和环境模板三处固定为 `cloud/off`。

`local/off` 与 `cloud/off` 都使用 synthetic local admin，免登录且不创建账号，并隐藏登录、注册、用户和项目成员管理入口。区别是 `cloud/off` 继续强制外置数据目录、锁定网页设置修改并要求 AI 任务操作人昵称；`cloud/required` 未登录时只能看到登录/注册页，自助注册创建启用状态的 `member`，不会自动加入既有项目。

三个 profile 共用业务代码和数据模型；切换 profile 不迁移、不删除项目、业务数据或文件，继续使用版本目录外的同一份 `LWS_DATA_ROOT` 和 `settings.local.json`，但会清除不兼容的服务端和浏览器会话，防止旧会话复活。

### 首次管理员

本节只适用于 `cloud/required`。无账号制品不得配置管理员引导变量。

首次以强制登录模式启动且用户表为空时，必须在 `/etc/lwstudio/lws.env` 中提供：

```bash
LWS_ADMIN_USER=admin
LWS_ADMIN_PASSWORD=replace-with-a-strong-bootstrap-password
```

两者缺一时服务会 fail-closed。也可在启动前直接创建或重置管理员：

```bash
LWS_DATA_ROOT=/srv/lwstudio/data \
LWS_ADMIN_PASSWORD='replace-with-a-strong-bootstrap-password' \
python3.11 scripts/create_admin.py --username admin
```

初始管理员必须在首次登录后修改密码。完成引导后，从环境文件移除 `LWS_ADMIN_PASSWORD`，重启服务并确认现有账号仍可登录。

### Cookie、HTTPS 与权限

- `cloud/required` 会话保存在服务端，浏览器使用带 `Secure` 的 `HttpOnly` cookie，因此公网入口必须是 HTTPS；`cloud/off` 不创建登录会话，但线上入口仍应使用 HTTPS。
- Nginx/CDN 必须原样转发请求 `Cookie` 和响应 `Set-Cookie`，并禁止缓存带 `Set-Cookie` 或 `Cache-Control: no-store` 的响应。
- 全局角色为 `admin`、`ops`、`member`；非管理员只能看到自己所属项目。管理员管理用户，管理员或有权限的运营人员管理项目成员。
- `cloud/off` 不执行上述账号和项目成员隔离；所有可访问者共享 synthetic admin 业务权限，因此只能用于可信内网。
- 完整路由能力表见 `docs/ROUTE_CAPABILITIES.md`。

## 发布

```bash
release=/srv/lwstudio/releases/20260716-<git-sha>
sudo ln -sfn "$release" /srv/lwstudio/current
sudo systemctl restart lws.service
sudo nginx -t && sudo systemctl reload nginx
```

发布后至少验证：

```bash
curl -fsS https://ai-lwstudio.example.com/api/version
curl -fsS https://ai-lwstudio.example.com/api/health
curl -sSI https://ai-lwstudio.example.com/
curl -sSI https://ai-lwstudio.example.com/api/projects
PACKAGE_GIT_SHA="$(.venv/bin/python -c 'import json; print(json.load(open("PACKAGE_MANIFEST.json", encoding="utf-8"))["git_sha"])')"
.venv/bin/python check.py \
  --base-url https://ai-lwstudio.example.com \
  --expect-deployment-mode cloud \
  --expect-auth-mode off \
  --expect-runtime-profile cloud-off \
  --require-provider \
  --expect-version 1.7.1 \
  --expect-git-sha "$PACKAGE_GIT_SHA" \
  --check-frontend-assets frontend/dist/assets
```

验收时必须确认三方静态资源完全一致：线上 HTML 引用的哈希资源、`/api/version` 清单和本地 `frontend/dist` 来自同一发布包；`git_sha` 必须等于 `PACKAGE_MANIFEST.json` 中的本次发布提交。无账号制品的 `anonymous_projects` 必须确认未登录访问核心业务 API 返回 200，登录和注册接口返回 403，上传可读性探针通过。还需确认 API 最终响应头包含 `no-store`、HTML 最终响应头包含 `no-cache`、健康检查中的数据目录/上传目录/数据库均可用。

完整业务冒烟测试：

```bash
.venv/bin/python scripts/stability_check.py \
  --base-url https://ai-lwstudio.example.com
```

该脚本会保留 `X-Operator: stability-check` 留痕，并用同一登录会话创建临时项目，覆盖上传、分析、术语导入、翻译、QA、归档和公告准备，结束后删除测试项目。

## 备份与恢复

备份对象只有 `/srv/lwstudio/data` 和 `/etc/lwstudio/lws.env`，其中前者包含数据库、上传、运行记录、产物和 provider 密钥。备份前短暂停止服务，避免 SQLite 与文件产物处于不同时间点：

```bash
sudo systemctl stop lws.service
sudo tar -C /srv/lwstudio -czf /secure-backup/lwstudio-data-$(date +%F-%H%M%S).tgz data
sudo cp -a /etc/lwstudio/lws.env /secure-backup/lws.env-$(date +%F-%H%M%S)
sudo systemctl start lws.service
```

恢复时先停止服务，把整份 `data/` 恢复到同一路径并修正所有者，再启动服务；不要只恢复 SQLite 而遗漏上传和产物文件。

## 回滚

代码回滚不回滚数据：把 `current` 切回上一 release，重启后端并重载 Nginx。执行前确认旧版本兼容当前数据库结构；若本次发布包含不可逆数据迁移，必须先恢复与该版本匹配的完整 `data/` 备份。

```bash
sudo ln -sfn /srv/lwstudio/releases/<previous-release-id> /srv/lwstudio/current
sudo systemctl restart lws.service
sudo nginx -t && sudo systemctl reload nginx
```

回滚后重复公网版本、缓存头、上传和下载验收。确认新旧 release 都不再使用后再删除旧版本目录，至少保留一个已验证可回滚版本。
