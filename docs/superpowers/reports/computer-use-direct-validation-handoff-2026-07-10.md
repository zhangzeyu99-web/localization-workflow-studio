# Computer Use 直接任务验收 Handoff

日期：2026-07-10

## 目标

在普通用户直接创建的 Codex 任务中，用 Computer Use 完成本地化工作台的 Windows 级交互与截图验收，并把证据写回现有 Sites 优化报告。

当前项目代码、浏览器验收和自动化测试均已完成。不要重新设计页面，不要重复修复已经通过的前端功能。

## 当前基线

- 仓库：`D:\codex\localization-workflow-studio`
- 分支：`codex/frontend-f5-sol-ux`
- 已推送提交：`c8e26eb42131a690197ca48a286523295066d099`
- 工作树：clean
- 本地地址：`http://127.0.0.1:5173`
- 局域网地址：`http://10.3.32.38:5173`
- 前端构建：通过
- Playwright E2E：31/31 通过
- Chrome 扩展：交互、DOM、控制台和横向溢出检查通过
- 主报告：`docs/superpowers/reports/sites-optimization-2026-07-10.md`

## 为什么必须换直接任务

当前任务的运行元数据为 `thread_source=subagent`，因此没有 `nodeRepl.nativePipe` 和 `nodeRepl.launchServices`。这是 Codex Desktop 的信任边界，不能通过重启服务、重新导入模块或自建协议绕过。

新任务开始后先验证：

- 在仓库根目录运行 `powershell -ExecutionPolicy Bypass -File scripts/verify-computer-use-runtime.ps1`，结果应为 `PASS`
- `thread_source` 不再是 `subagent`
- `nodeRepl.nativePipe.createConnection` 可用，或宿主提供等价的受信任启动能力
- Computer Use skill 的标准 bootstrap 能读取 `sky.documentation("guidance")`

如果仍无受信任管道，停止重复修包；确认新任务确实是用户从侧栏直接创建，而不是委派、接管或自动继续任务。

## 本机运行包修复状态

Codex Desktop 2026-07-10 安装包存在 URL 编码未还原和依赖漏包。当前机器已完成以下可逆修复：

- `%40img`、`%40napi-rs`、`%40oai`、`%40statsig` 已恢复标准 `@scope` 目录联接
- `%24_StatsigGlobal.js` 和对应类型文件已恢复 `$` 文件名硬链接
- Sky 构建产物需要的 `tslib@2.8.1` 已补齐
- Sky 主模块已通过完整导入检查

Codex Desktop 更新可能覆盖这些修复。只有 Sky 导入再次失败时才复查；不要预先复制整套 `node_modules`，不要启动自定义 Computer Use helper。

## 必做验收

严格使用安装好的 `computer-use` skill。先完整读取 `guidance` 和需要的 API 文档，再控制 Windows 应用。

1. 打开或激活显示 `http://127.0.0.1:5173` 的 Chrome 窗口，截取工作台项目总览。
2. 在 `Repro Manual Fix` 项目进入“新翻译任务”，打开 `8 QA 校对`。
3. 验证右侧只保留一个 QA 结论区，校对文件显示“已译语言表（EN）”，不出现 `QA final workbook` 或 `result_en`。
4. 返回项目总览，进入“交付”，验证带问题交付包含最终译文、修改记录和 QA 摘要入口。
5. 切换到 `金手指` 项目并进入“公告翻译”，验证 `KR 韩语` 子流程显示“需继续/修复”，选中态为青色而不是旧紫色。
6. 至少执行一次真实点击和一次滚动，确认控件可操作、吸顶导航不遮挡内容、页面无横向溢出。
7. 检查 Windows 截图中没有文本重叠、截断、空白主区域或功能入口缺失。

## 截图产物

使用 Computer Use 的 Windows.Graphics.Capture 结果，不要用 Playwright 截图冒充。保存为：

- `docs/superpowers/reports/assets/computer-use-2026-07-10/01-overview-windows.png`
- `docs/superpowers/reports/assets/computer-use-2026-07-10/02-qa-step8-windows.png`
- `docs/superpowers/reports/assets/computer-use-2026-07-10/03-delivery-windows.png`
- `docs/superpowers/reports/assets/computer-use-2026-07-10/04-announcement-windows.png`

将四张图逐张展示在线程中，并更新 `sites-optimization-2026-07-10.md` 的 Computer Use 状态和截图章节。

## 完成门禁

- Computer Use 确实获得受信任 Windows 管道
- 四个场景均有 Windows 级截图
- 至少一个点击和一个滚动由 Computer Use 完成
- 页面行为与现有 31 条 E2E 结果一致
- 更新后的中文报告通过 `output_quality_gate.py --expect-cjk`
- `git diff --check` 通过
- 新证据已提交并推送到 `codex/frontend-f5-sol-ux`

只有以上项目全部满足，才可以把“继续完成优化”目标标记为完成。

## 新任务输入

在 Codex 侧栏新建普通任务并发送：

> 在 `D:\codex\localization-workflow-studio` 完成 Computer Use 最终验收。先读取 `docs/superpowers/reports/computer-use-direct-validation-handoff-2026-07-10.md`，严格按 handoff 执行并提交推送。不要读取旧大线程。
