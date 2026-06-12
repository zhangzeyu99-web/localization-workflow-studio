# 本地化工作台公网运行生产化计划

## 结论

当前系统已经具备单机完整业务闭环：上传文件进入私有 `LWS_DATA_ROOT`，SQLite 记录项目、任务和产物，后端解析上传内容生成 prompt/workpack，再分批调用 AI provider。

距离真正公网运行的主要差距不在业务流程，而在生产部署、持久化可靠性、任务调度、备份清理和运维自检。第一阶段建议先做“单实例公网可用版”，暂不处理账号、权限和租户隔离。

## 当前源码运行模型

- 后端数据根目录由 `LWS_DATA_ROOT` 决定；默认是 `D:\codex\localization-workflow-studio-data`。
- 私有配置写入 `<LWS_DATA_ROOT>\settings.local.json`。
- SQLite 数据库写入 `<LWS_DATA_ROOT>\studio.sqlite3`。
- 上传文件、项目资料、AI 中间产物、QA 产物和交付文件都写在同一个 data 根目录下。
- 前端调用 `frontend/src/apiClient.ts` 里的 `API` 前缀；开发模式通过 Vite proxy 把 `/api` 转发到后端。
- 生产模式不应继续依赖 Vite dev server，应使用前端静态构建产物和反向代理。

## 目标架构

第一阶段目标是单实例公网运行：

```text
Browser
  -> HTTPS frontend domain
  -> static frontend files
  -> /api reverse proxy
  -> one FastAPI backend instance
  -> private persistent LWS_DATA_ROOT
  -> SQLite + uploaded files + generated artifacts
```

必须满足：

- 所有 `/api` 请求稳定打到同一个后端实例。
- 同一个后端实例读写同一个持久 `LWS_DATA_ROOT`。
- `LWS_DATA_ROOT` 不直接暴露为公网静态目录。
- 重启后端后，项目、上传文件、run 记录和交付文件仍可读取。

## 必要环境变量

公网后端至少设置：

```powershell
$env:LWS_DEPLOYMENT_MODE = "cloud"
$env:LWS_DATA_ROOT = "D:\lws-data"
$env:LWS_CORS_ORIGINS = "https://your-web-domain.example.com"
$env:LWS_MAX_UPLOAD_MB = "200"
```

说明：

- `LWS_DEPLOYMENT_MODE=cloud` 用于健康检查和云端验收标识。
- `LWS_DATA_ROOT` 必须是后端可读写的持久目录，不要放在仓库目录、临时目录或容器临时层。
- `LWS_CORS_ORIGINS` 必须包含真实前端域名。
- `LWS_MAX_UPLOAD_MB` 默认 200，可按公网反代和磁盘容量调整。

## Data 目录结构

建议生产 data 目录结构如下：

```text
<LWS_DATA_ROOT>/
  settings.local.json
  studio.sqlite3
  projects/
    proj_xxx/
      uploads/
        original-upload.xlsx
        .chunks/<upload_id>/*.part
        .translation_cache/<lang>.jsonl
      profile/
        project_profile_<lang>.json
        translation_prompt_<lang>.txt
        project_brief_<lang>.md
        project_material_packet.json
        project_analysis_report.md
        project_harness.json
        video_frames/<artifact_id>/frame_01.png
      glossary/
        curated_terms.json
        observed_terms.json
        exports/
      translations/
        exports/
      delivery/
        delivery_package_or_files
      assets/
      runs/
  runs/
    run_xxx/
      logs/
      translation/
        snapshots/
        translation_workpack.jsonl
        batch_manifest.json
        batches_<batch_size>/
        translation_response.jsonl
        translation_manifest.json
        *_最终版.xlsx
        qa/
      announcement_lookup/
      announcement_terms/
      announcement_prepare/
      announcement_translate/
      qa/
      model_fixes/
      manual_fixes/
      semantic_qa/
      glossary/
  uploads/
    diagnostics/
  diagnostics/
    latest_upload_readability.json
  templates/
```

关键边界：

- `projects/<project_id>/uploads/` 保存用户上传原始文件。
- `projects/<project_id>/profile/` 保存项目分析结果、项目 prompt 和 harness。
- `runs/<run_id>/` 保存每次执行的中间文件、AI 请求/响应、QA 和交付产物。
- `studio.sqlite3` 是索引和状态源；文件系统保存实际文件。

## 上传内容结构

上传入口：

- `POST /api/projects/{project_id}/files`
- `POST /api/projects/{project_id}/files/chunk`

上传流程：

1. 后端清洗文件名。
2. 按 `kind` 校验扩展名。
3. 写入 `.uploading` 临时文件或 `.chunks/` 分片目录。
4. 完整上传后移动到 `projects/<project_id>/uploads/`。
5. 计算 sha256。
6. 写入 `artifacts` 表，记录 `id/project_id/run_id/label/kind/role/origin/metadata/path/mime/size`。

常见 kind：

- `language_table`：语言表输入，支持 xlsx/xls/csv。
- `final_workbook`：已有译文或 QA 输入表。
- `quick_input`：快速任务输入，支持 xlsx/xls/csv/txt/md。
- `asset`：项目资料。
- `term_base` / `glossary_final`：术语表。
- `announcement_ai_response`：公告 AI 响应导入。

## AI 读取链路

AI 不直接读取 data 目录，也不直接读取完整原始 Excel。后端会先把文件解析成受控上下文。

### 项目分析

1. 前端提交 `asset_artifact_ids`。
2. 后端从 `artifacts.path` 读取上传文件。
3. `build_project_material_packet()` 解析 txt/md/docx/pdf/xlsx/csv/json；图片/视频在有真实 provider 时做视觉分析。
4. 生成：
   - `project_material_packet.json`
   - `project_profile_<lang>.json`
   - `translation_prompt_<lang>.txt`
   - `project_brief_<lang>.md`
   - `project_analysis_report.md`
5. AI 输入摘要读取 material packet，展示哪些文件进入了 AI。

### 语言表翻译

1. run metadata 记录 `input_artifact_id`。
2. 后端读取语言表 artifact 的 `path`。
3. 本地 harness 生成 `runs/<run_id>/translation/translation_workpack.jsonl`。
4. 每行 workpack 包含 `id`、`source`、`term_hits` 等字段。
5. 后端生成 prompt snapshot 和 glossary snapshot。
6. `_translate_rows_with_orchestration()` 按 batch 分组、限流、重试。
7. provider 收到的是“Project guidance + Rows JSONL”，不是整个上传文件。
8. AI 返回 JSONL 后，后端校验 id、顺序、placeholder、tag、newline，再写回 workbook 并跑 QA。

### 公告翻译

1. 公告材料先解析为 segments。
2. lookup 阶段写入公告术语命中和 prompt context。
3. prepare 阶段生成每种语言的：
   - announcement workpack JSONL
   - prompt snapshot
   - manifest
4. translate 阶段读取 workpack 和 prompt snapshot，复用同一批量翻译 orchestration。
5. apply/QA/delivery 阶段把 AI 响应写回公告交付文件。

## 当前距离真正线上运行的差距

### 第一优先级

- 生产启动方式：补充后端生产启动命令或服务文件，避免继续使用本地脚本的 Vite dev server。
- 反向代理：明确 `/api` 转发到 FastAPI，静态资源由前端构建产物提供。
- 持久 data：确认 `LWS_DATA_ROOT` 是可备份、可扩容、可监控的持久磁盘。
- 单实例粘性：所有请求必须命中同一个后端实例，避免上传在 A、分析在 B。
- 健康检查：上线前必须跑 `/api/health` 和 `/api/diagnostics/upload-readability`。

### 第二优先级

- 备份恢复：定期备份 `studio.sqlite3` 和 `projects/`、`runs/`。
- 清理策略：按项目、run、上传时间清理中间文件和旧交付包。
- 日志：保留后端访问日志、workflow 子进程日志、AI batch 错误日志。
- 任务恢复：补充长任务中断后恢复、取消、重试的运维说明。
- 容量监控：监控 data 目录大小、单项目上传量、run 产物大小。

### 后续阶段

- SQLite 迁移 Postgres。
- 文件系统迁移对象存储。
- 进程内 background thread 迁移任务队列。
- 多实例横向扩容。
- 多用户、权限、租户隔离。

## 验收标准

上线前至少通过：

1. `GET /api/health`
   - `deployment_mode = cloud`
   - `storage.data_root_writable = true`
   - `storage.uploads_writable = true`
   - `database.connected = true`
   - `provider.provider_configured = true`

2. `POST /api/diagnostics/upload-readability`
   - `ok = true`
   - `readable = true`
   - 有 `sha256`
   - txt/md/csv/json 有 `preview`
   - 再查 `/api/health` 能看到 `latest_upload_readability`

3. 项目资料上传和 AI 分析
   - 上传文件出现在 `projects/<project_id>/uploads/`
   - artifact 表记录正确
   - AI 输入摘要显示文件名、解析状态、是否进入 AI
   - 不可解析文件给出明确提示

4. 语言表翻译
   - 生成 `translation_workpack.jsonl`
   - 生成 `batch_manifest.json`
   - AI response 写入 `translation_response.jsonl`
   - QA 产物生成
   - 交付文件可下载

5. 公告翻译
   - 生成分段和术语命中
   - 生成公告 workpack 和 prompt snapshot
   - AI 输入摘要可查看
   - 交付文件可下载

6. 重启验证
   - 后端重启后项目列表仍存在
   - artifact 下载正常
   - run 详情正常
   - delivery 文件正常

## 默认范围

第一阶段只解决“公网单实例可靠运行”。暂不处理：

- 登录账号
- 用户权限
- 多租户隔离
- 审计合规
- 计费
- 多实例调度

这些内容进入后续生产化阶段。
