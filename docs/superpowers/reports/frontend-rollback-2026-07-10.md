# 前端 1.2.0 回滚基线

## 基线

- 创建日期：2026-07-10
- 基线提交：`5e67b44aaed63b853da34b03c7e3628f087cab10`
- 本地标签：`frontend-v1.2.0-pre-ux-20260710`
- 本地备份分支：`backup/frontend-v1.2.0-pre-ux-20260710`
- 前端归档：`release_archives/frontend-v1.2.0-pre-ux-20260710.zip`
- SHA-256：`3cebb5763c15df81f64fe2fc4ed1ebe1b94abd75800ff7a84fdefda423ab32e7`

标签、备份分支和归档均指向前端优化前的 1.2.0 版本。`release_archives/` 已被 Git 忽略，归档只保存在本机。

## 推荐恢复方式

保留当前工作区，在相邻目录检出旧版：

```powershell
git worktree add ..\localization-workflow-studio-frontend-v1.2.0 frontend-v1.2.0-pre-ux-20260710
```

在当前仓库切换到备份分支：

```powershell
git switch backup/frontend-v1.2.0-pre-ux-20260710
```

仅恢复旧版前端目录时，先提交或另存当前改动，再执行：

```powershell
git restore --source frontend-v1.2.0-pre-ux-20260710 -- frontend
```

Git 引用不可用时，可从本机归档恢复到临时目录：

```powershell
Expand-Archive -LiteralPath .\release_archives\frontend-v1.2.0-pre-ux-20260710.zip -DestinationPath .\frontend-v1.2.0-restored
```

## 校验

```powershell
$expected = ((Get-Content .\release_archives\frontend-v1.2.0-pre-ux-20260710.sha256) -split '\s+')[0]
$actual = (Get-FileHash .\release_archives\frontend-v1.2.0-pre-ux-20260710.zip -Algorithm SHA256).Hash.ToLowerInvariant()
$expected -eq $actual
```

预期输出为 `True`。归档已验证可读取，共包含 87 个条目。
