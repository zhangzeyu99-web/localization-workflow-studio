# 上游更新应用到项目的流程规划（2026-07-08）

> 目标：两个持续迭代的技术仓库的更新，能以可控、可验证、可回滚的方式进入 Localization Workflow Studio，不破坏产品稳定性。
> 本文档完全基于项目既有机制（验证分层 Tier A–E、QUALITY_GATES、STABILITY_TEST_LIST、validation_set、failure_log/improvement_backlog、版本一致性检查、fable5 审计循环模式），不发明平行体系。

---

## 0. “两个技术仓库”判定结论

### 主判定（证据充分，按此规划）

`docs/ITERATION.md` 明确写着本项目是 “an integration shell around two upstream workflow projects”，README 也说明主仓库内置了两个底层 workflow 副本，上游仓库“只作为底层技术源仓库/上游开发仓库使用”。两个技术仓库即：

| 上游仓库 | 本地路径 | remote | 对应内置副本 | 最近迭代 |
|---|---|---|---|---|
| `zhangzeyu99-web/localization-workflow` | `D:\project\localization-workflow-project` | github.com/zhangzeyu99-web/localization-workflow.git | `workflow/localization`（翻译、QA、回填、交付核心） | 2026-06-01 |
| `zhangzeyu99-web/glossary-extraction-workflow` | `D:\codex\glossary-extraction-workflow` | github.com/zhangzeyu99-web/glossary-extraction-workflow.git | `workflow/glossary`（术语提取、公告术语反查、AI 漏词补充核心） | 2026-07-07 |

两个仓库确实都在持续更新，符合用户描述“两个技术仓库都有做持续更新优化迭代”。

### 已排除的候选

- `D:\codex\localization-workflow-studio-4399-publish`、`D:\codex\lws-verify-audit`：与主仓库同一 remote，是发布/审计用工作副本，属下游，不是更新来源。
- `D:\codex\aifanyi-release-git4399`：无 remote 的本地发布包仓库，属交付产物。
- `D:\codex\codex`（Agent 工具仓库）：确实持续迭代，但按 README/AGENTS 规则它不是产品运行依赖，只影响 Agent 侧门禁脚本。若用户实际指“本项目 + codex 工具仓库”，本流程同样适用：codex 工具仓库更新按本文第 3 节的“Agent 侧工具更新”通道处理（只需 Tier A + 相关 gate 脚本自测，不触碰产品运行时）。

### 上游 → 内置副本的同步映射

内置副本只取上游的技术子集，不是整仓库拷贝：

```text
localization-workflow 上游          →  workflow/localization
  utils/ scripts/ templates/ tests/ fixtures/
  cli.py process_language.py workspace_runner.py requirements.txt
  （不同步：output/ tmp/ tools/ gui.py debug.log 示例文档等）

glossary-extraction-workflow 上游   →  workflow/glossary
  scripts/ templates/ tests/ fixtures/ data/ docs/ examples/
  requirements.txt README.md
  （不同步：tmp/ .github/ VERSION 等仓库自身元数据）
```

同步映射的三条补充规则（来自 2026-07-08 试跑复盘）：

- **只认已提交内容**：上游工作树若有未提交 WIP，一律不纳入同步；等上游提交后下个周期再评估。
- **副本领先上游时不反向覆盖**：diff 中副本侧独有的内容（如 ko/ja 支持、大文本 gate 三件套、unicode 修复）默认视为本项目的本地化保留项，需要时另走"回馈上游"通道，绝不在同步批次里用上游版本覆盖。
- **README 同步剔除坏链**：上游 README 若链接了映射中不同步的文件（如 CHANGELOG.md、VERSION），同步时剔除这些链接或连带同步被引用文件，不引入坏链。

---

## 1. 既有稳定性资产盘点（流程的地基）

| 资产 | 位置 | 在更新流程中的角色 |
|---|---|---|
| 验证分层 Tier A–E | `docs/superpowers/plans/2026-07-08-fable5-full-audit-refactor-loop.md` Validation Tiers 章节 | 分级验证的唯一标准，本文直接复用其命令 |
| 质量门禁 | `docs/QUALITY_GATES.md` | 上游变更不得破坏四道 gate（prompt/pre-translation/pre-backfill/pre-delivery）和正式翻译证据链 |
| 稳定性验收清单 | `docs/STABILITY_TEST_LIST.md` | 部署后 Tier D 验收的必测项与失败即阻断项 |
| 手工验证集 | `docs/optimization/validation_set/cases/001–008` | 大变更合并前的人工回归 |
| 失败沉淀机制 | `docs/optimization/failure_log.md` + `improvement_backlog.md` | 更新引入的失败必须登记，同类失败 2 次升优先级 |
| 版本一致性 | `VERSION` + `/api/version` + 前端 bundle 版本注入 + `deployment_check --expect-version --check-frontend-assets` | 更新合并后版本号联动，部署后机器检查 |
| 兼容边界契约 | `docs/ITERATION.md` Compatibility Boundary | 上游同步的破坏性判定依据（见第 2 节） |
| 版本联动文件清单 | `docs/GITHUB_MANAGEMENT.md` 版本管理章节 | `VERSION`、`backend/app/main.py`、`frontend/package.json(+lock)`、`README.md`、`CHANGELOG.md`、`docs/releases/vX.Y.Z.md` |
| fable5 审计循环 | 同上 fable5 计划：Architect 决策 + Executor 执行 + Validator 复核 | 破坏性变更的执行模式 |

Tier A–E 命令速记（与 fable5 计划完全一致）：

```powershell
# Tier A：任何代码批次
python -m compileall -q backend workflow scripts
python -m ruff check backend/app backend/tests scripts --select E9,F
npm --prefix frontend run build            # 前端有改动时

# Tier B：workflow 相关批次
python -m pytest backend/tests/test_risk_hardening.py backend/tests/test_workflow_e2e.py backend/tests/test_multilingual_orchestration.py backend/tests/test_multilingual_delivery.py -q
# 上游基线套件必须分别在各自目录内执行（仓库根的 pytest.ini pythonpath 只服务 backend，
# 从根目录跑会 ModuleNotFoundError）：
Push-Location workflow\localization; python -m pytest tests -q; Pop-Location
Push-Location workflow\glossary; python -m pytest tests -q; Pop-Location
npm --prefix frontend run e2e -- --workers=1

# Tier C：全量本地信心（172 pytest + 22 e2e）
python -m compileall -q backend workflow scripts
python -m ruff check backend/app backend/tests scripts --select E9,F
python -m pytest -q
npm --prefix frontend run build
npm --prefix frontend run e2e -- --workers=1

# Tier D：运行时与部署信心（28 步稳定性检查）
python scripts\deployment_check.py --base-url http://127.0.0.1:5174 --expect-version (Get-Content VERSION) --check-frontend-assets
python scripts\stability_check.py --base-url http://127.0.0.1:5174

# Tier E：打包信心（打包/部署文件变更时）
python scripts\build_release_package.py
```

### 兼容边界契约（破坏性判定依据）

来自 `docs/ITERATION.md`，上游变更若破坏以下任一条即判定为破坏性变更：

1. `run_translation_harness.py` 输出 `translation_workpack.jsonl` + `translation_manifest.json`，接受 JSONL 响应。
2. 翻译 provider 输出保持 `id + translation` 的 JSONL。
3. `run_quality_harness.py --json` 返回含 `passed`、`issues`、`failures` 的 JSON 对象。
4. `extract_glossary.py` 接受 ID/source/target 列参数，输出术语明细、最终术语表、project brief、prompt 产物。

注意：`docs/ITERATION.md` 第 31 行写的适配层 `backend/app/workflow.py` 已演进为 `backend/app/workflow/` 包（translation.py、qa.py、glossary.py、delivery.py 等）。契约被破坏时应在同一批次内修改对应的适配模块，并顺手修正 ITERATION.md 的这一处文档漂移。

---

## 2. 更新分类分级表

| 类别 | 典型例子 | 验证等级 | 版本影响 | 执行模式 |
|---|---|---|---|---|
| U1 依赖升级（兼容小版本） | fastapi/pandas/openpyxl patch 或 minor；react/vite minor | Tier A + Tier B（受影响面），后端全依赖升级时直接 Tier C | 无或 PATCH | 轻量批次，批量做 |
| U2 依赖升级（大版本/框架级） | pandas 2→3、react 19→20、vite 大版本、Python 版本 | Tier C + Tier D，前端大版本另跑全部 e2e | PATCH 或 MINOR | 轻量批次但独立分支，一次只升一个大件 |
| U3 上游功能同步（契约不变） | 上游 utils/scripts 优化、新增 gate 规则、测试补充 | Tier B（上游基线套件 + 受影响 workflow）+ 每三批 Tier C | PATCH 或 MINOR | 轻量批次 |
| U4 安全补丁 | 依赖 CVE、上传路径/鉴权问题修复 | Tier A + Tier B 加急，合并后 24h 内部署并 Tier D | PATCH | 即时做，插队 |
| U5 破坏性变更 | 上游改变第 1 节四条契约任一条；DB schema/artifact 契约变化；QA 语义变化 | Tier C + Tier D + Tier E，外加手工验证集相关 case | MINOR 或 MAJOR | fable5 审计循环模式（见第 6 节） |
| U6 Agent 侧工具更新（若含 codex 工具仓库理解） | `D:\codex\codex` 中 gate/retro 脚本、`localization_pack_gate.py` 等 | Tier A + 对应脚本自测（如 `run_large_text_multilingual_gate.py` 的 dry-run） | 无（不是产品运行依赖） | 轻量批次，不触碰产品运行时 |

分级原则：先按“契约是否被破坏”把 U3 和 U5 分开，再按“是否影响产品运行时”把 U6 剥离；拿不准时按更高一级处理。

---

## 3. 更新引入流程（六步，每步给命令）

### 第 1 步：发现与登记

每次更新周期开始，先只读地看上游动了什么：

```powershell
# 上游拉取最新（在上游仓库操作，不动主仓库）
git -C D:\project\localization-workflow-project fetch origin
git -C D:\codex\glossary-extraction-workflow fetch origin

# 看两个上游自上次同步以来的提交
# <last-sync-commit> 从主仓库同步提交记录取：git log --oneline --grep="sync" -- workflow/
# 同步 commit message 固定格式：chore: sync <scope> (<repo> <upstream-hash>[, ...])，
# 例：chore: sync upstream subset (localization b5a4a0d, glossary a96a919/9d8d78f)
git -C D:\project\localization-workflow-project log --oneline <last-sync-commit>..origin/HEAD
git -C D:\codex\glossary-extraction-workflow log --oneline <last-sync-commit>..origin/HEAD
```

把候选更新按第 2 节分类，登记到 `docs/optimization/improvement_backlog.md`（状态“待评估”）或直接进入本流程（U4 安全补丁）。

### 第 2 步：隔离分支（推荐用 worktree）

```powershell
cd D:\codex\localization-workflow-studio
git fetch origin
git worktree add D:\codex\lws-upstream-sync -b codex/update-<scope>-<yyyymmdd> origin/master
# 例：codex/update-glossary-sync-20260708、codex/update-deps-python-20260801
# 收口后：git worktree remove D:\codex\lws-upstream-sync
```

规则：一个分支只装一类更新（U1–U6 不混装）；U2 大版本升级一个分支只升一个大件。用 worktree 而非在主仓库 `git switch`，避免与并行会话争用主工作树；worktree 内跑 pytest 前先清理/隔离 `LWS_DATA_ROOT`、`PYTHONPATH`、`TEMP` 等环境变量，防止共享测试数据目录串扰。

### 第 3 步：变更影响面评估 → 决定 Tier B 范围

先做只读 diff，确认改了哪些文件。直接对上游工作树 diff 会被 `__pycache__`/`.pyc`/未提交 WIP 淹没且方向失真，必须先导出上游 HEAD 的干净快照：

```powershell
# 先导出上游已提交内容的干净快照，再和内置副本比较
git -C D:\project\localization-workflow-project archive HEAD | tar -x -C D:\codex\tmp-upstream-snapshot
git diff --no-index --stat workflow\localization\utils D:\codex\tmp-upstream-snapshot\utils
git diff --no-index --stat workflow\glossary\scripts <glossary 快照>\scripts
# 比较结果按第 0 节补充规则分方向处置：上游领先→候选同步；副本领先→本地化保留，不反向覆盖
```

按文件落点映射到受影响 workflow，决定验证范围：

| 变更落点 | 受影响 workflow | 最小验证范围 |
|---|---|---|
| `workflow/localization/utils|scripts` | 翻译、QA、交付、大文本 gate | `pytest workflow/localization/tests -q` + Tier B 后端四件套 |
| `workflow/glossary/*` | 术语、公告 | `pytest workflow/glossary/tests -q` + `pytest backend/tests -k "glossary or announcement" -q` |
| `backend/requirements.txt` | 全后端 | Tier C |
| `frontend/package.json` | 全前端 | `npm --prefix frontend run build` + `npm --prefix frontend run e2e -- --workers=1` |
| `workflow/*/requirements.txt` | 对应 workflow 套件 | 对应上游基线套件 + Tier B |
| 同时落在两个及以上 workflow | 跨流程 | 直接 Tier B 全量，按 fable5 规则需 Architect 检查点 |

同时对照第 1 节四条契约逐条判定：任何一条被破坏 → 改判 U5，转第 6 节循环模式。

### 第 4 步：应用变更 + 分级验证

- U1/U4：改 `requirements.txt` / `package.json` 后重装依赖，跑对应 Tier。
- U3：把上游变更按第 0 节同步映射复制进内置副本（只复制技术子集），在 commit message 或 CHANGELOG 记录上游 commit 号（ITERATION.md 要求）。
- 所有类别：验证不过不合并；同一验证类失败两次即停下这条路，登记 blocker（fable5 规则 8）。

```powershell
# 按第 2 节分级表执行对应 Tier，例如 U3（基线套件分目录执行，见第 1 节说明）：
Push-Location workflow\localization; python -m pytest tests -q; Pop-Location
Push-Location workflow\glossary; python -m pytest tests -q; Pop-Location
python -m pytest backend/tests/test_risk_hardening.py backend/tests/test_workflow_e2e.py backend/tests/test_multilingual_orchestration.py backend/tests/test_multilingual_delivery.py -q
npm --prefix frontend run e2e -- --workers=1
```

### 第 5 步：版本联动 + 合并

用户可见的变更按 `docs/GITHUB_MANAGEMENT.md` 联动版本号（PATCH/MINOR/MAJOR 判定见该文档），同步更新：`VERSION`、`backend/app/main.py`、`frontend/package.json(+lock)`、`README.md`、`CHANGELOG.md`、`docs/releases/vX.Y.Z.md`。

```powershell
git add <本批次明确文件>        # 禁止 git add .
git commit -m "chore: sync glossary upstream ae37b4e"   # 记录上游 commit
git push -u origin codex/update-<scope>-<yyyymmdd>
# PR 描述按 GITHUB_MANAGEMENT.md：改了什么/为什么/影响面/验证命令/是否影响数据目录、artifact、provider、QA 输出格式
```

合并前若为 U2/U5，先跑手工验证集相关 case（`docs/optimization/validation_set/cases/`，尤其 001、002、006、008）。

### 第 6 步：部署后 Tier D 验收 + 打 tag

```powershell
# 部署后（本地或线上）验收
python scripts\deployment_check.py --base-url <部署地址> --expect-version (Get-Content VERSION) --check-frontend-assets
python scripts\stability_check.py --base-url <部署地址>
# 线上另加：--require-cloud --require-provider（见 STABILITY_TEST_LIST.md）

# 通过后打回滚锚点
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z

# 打包部署形态时刷新发布包（Tier E）
python scripts\build_release_package.py
```

验收失败按 `STABILITY_TEST_LIST.md` “失败即阻断”清单处理，同时把失败登记进 `docs/optimization/failure_log.md`（模板见该文件），必要时回滚。

---

## 4. 回滚策略（两层）

### 第 1 层：git 回滚（源码级）

- 每次更新合并部署后都有版本 tag（第 3 步第 6 小节），tag 即回滚锚点。
- 已合并未部署：`git revert <merge-commit>`（不用 reset，保留历史）。
- 已部署出问题：

```powershell
git switch master
git revert -m 1 <merge-commit>      # 或直接从上一个 tag 重建部署
git push origin master
```

### 第 2 层：部署产物回滚（运行时级）

- `build_release_package.py` 生成的历史发布包是现成的回滚产物；发布包按版本留存（当前实践见 `tmp/release-check-extract/` 与 4399 发布仓库）。
- 回退步骤：停服务 → 用上一版发布包重新部署 → 数据目录（`lws-data`、SQLite、uploads/runs/projects/artifacts）不在发布包内、天然保留 → 重启。
- 回滚后必须重新跑 Tier D 双命令，`--expect-version` 填回退后的版本号，确认 `/api/version`、前端 bundle 版本、健康检查全部一致，才算回滚完成。
- 涉及 DB schema 的 U5 变更必须在合并前写明“schema 是否可逆、不可逆时的数据备份命令”，否则不许合并——这是 U5 走 fable5 循环的原因之一。

### 回滚决策线

- Tier D 任何“失败即阻断”项失败且 30 分钟内无法定位 → 回滚。
- 正式翻译证据链（QUALITY_GATES 四道 gate）任何一道被破坏 → 立即回滚，不等定位。

---

## 5. 节奏建议

| 节奏 | 适用 | 说明 |
|---|---|---|
| 即时做（24h 内） | U4 安全补丁；上游修复的正在影响本项目的 bug | 插队处理，Tier A+B 加急，部署后当天 Tier D |
| 按上游节奏做（1–2 周内） | U3 上游功能同步 | 上游出现有价值提交后拉一次同步分支；两个上游可以同一分支周期内各开一个分支，不合装 |
| 批量做（每月一批） | U1 依赖小版本升级 | 每月初集中升级 Python + npm 小版本，一个分支一次 Tier C 兜底，避免天天碎升 |
| 单独排期做 | U2 大版本升级、U5 破坏性变更 | 每次只做一件，走完整 Tier C+D（U5 另加 Tier E 和手工 case） |
| 冻结期不做 | 正式交付冲刺期、发布前 48h、有未收口的 P0 failure_log 条目时 | 冻结期内只允许 U4；冻结解除后先清积压的 U4/U1 再做 U3 |

---

## 6. 与既有 AGENTS.md 规则和 fable5 循环模式的衔接

### 大变更（U5、跨两个及以上 workflow 的 U3、涉及 DB/artifact/provider 契约的任何更新）→ 审计循环模式

按 `docs/superpowers/plans/2026-07-08-fable5-full-audit-refactor-loop.md` 的三角色模式执行：

- **Architect（Fable5）**：只在检查点介入——上游契约变化的适配方案、Module Interface 调整、DB/runtime 契约变更、发布就绪判定。用该计划的 “Fable5 Architecture Checkpoint” 紧凑交接包，不喂全仓库。
- **Executor（便宜模型）**：diff 阅读、同步复制、测试补写、机械适配、跑验证、写报告。
- **Validator**：diff 复核、验证输出分诊、回归风险检查。
- 升级触发条件直接复用该计划 “Model Budget And Dispatch Policy” 的触发清单（触碰两个以上 workflow、影响正式翻译证据/QA 语义/交付语义/provider/大文本 gate/打包规则、executor 两次失败等）。
- 模型调度记录进 `docs/superpowers/reports/model-dispatch-log.md`。

### 小变更（U1、单 workflow 的 U3、U4、U6）→ 轻量批次

按 fable5 计划的 “Required Cycle For Each Batch” 精简执行：定义批次 → （可行时）先写失败测试 → 最小变更 → 聚焦验证 → 批次 Tier → 提交。不需要 Architect 检查点，不需要 dispatch log。

### AGENTS.md 规则的落点

- 更新验证中涉及翻译输出的回归，一律区分“基础结构 QA”与“逐句审校”，不因是回归测试就放松表述（工作区规则）。
- 大文本 gate 相关的上游同步（`large_text_multilingual_gate/runner/retro`），验证时用产品内 `backend/app/workflow/multilingual.py` + `translation_orchestrator.py` 路径为准，Agent 脚本只做 preflight/dry-run 自测。
- 更新引入的任何真实失败按 failure_log 模板登记；能机器检查的失误沉淀成脚本或 gate（D:\codex 返工沉淀规则）。

---

## 7. 一页速查清单

```text
上游更新应用速查清单（每次更新照此执行）

[ ] 1. 分类：U1 依赖小版本 / U2 依赖大版本 / U3 上游功能同步 / U4 安全补丁 / U5 破坏性 / U6 Agent 工具
       判定破坏性：对照 ITERATION.md 四条契约（workpack+manifest、id+translation JSONL、
       quality_harness --json 结构、extract_glossary 参数与产物）
[ ] 2. 冻结期检查：交付冲刺 / 发布前 48h / 有未收口 P0 → 只放行 U4
[ ] 3. 隔离分支：git worktree add <路径> -b codex/update-<scope>-<yyyymmdd> origin/master
       一个分支只装一类更新；U2 一个分支只升一个大件；worktree 内清理测试环境变量
[ ] 4. 影响面评估：先 git archive 导出上游 HEAD 干净快照，再 git diff --no-index --stat
       内置副本 vs 快照；副本领先部分是本地化保留项，不反向覆盖
       localization utils/scripts → 翻译/QA/交付；glossary → 术语/公告；
       backend deps → Tier C；frontend deps → build + e2e；跨 2+ workflow → Fable5 检查点
[ ] 5. 应用变更：U3 只复制技术子集（utils/scripts/templates/tests/fixtures 等），
       commit message 记录上游 commit 号
[ ] 6. 分级验证（不过不合并；同类失败 2 次即停并登记 blocker）：
       U1 → Tier A+B（全后端依赖则 Tier C）
       U2 → Tier C+D
       U3 → 上游基线套件 + Tier B（每三批加一次 Tier C）
       U4 → Tier A+B 加急
       U5 → fable5 循环 + Tier C+D+E + 手工 case（001/002/006/008 起步）
       U6 → Tier A + gate 脚本自测
[ ] 7. 版本联动：VERSION / backend/app/main.py / frontend/package.json(+lock) /
       README / CHANGELOG / docs/releases/vX.Y.Z.md 同步改
[ ] 8. 合并：git add <明确文件>（禁 git add .）→ PR 按 GITHUB_MANAGEMENT.md 模板
[ ] 9. 部署后 Tier D 验收：
       python scripts\deployment_check.py --base-url <url> --expect-version (Get-Content VERSION) --check-frontend-assets
       python scripts\stability_check.py --base-url <url>
       线上另加 --require-cloud --require-provider
[ ] 10. 打 tag（回滚锚点）：git tag -a vX.Y.Z && git push origin vX.Y.Z
        打包形态刷新发布包：python scripts\build_release_package.py
[ ] 11. 失败处置：Tier D 阻断项 30 分钟定不了位 → 回滚（git revert + 上一版发布包重部署，
        回滚后重跑 Tier D）；失败登记 docs/optimization/failure_log.md
[ ] 12. 沉淀：可机器检查的失误写成脚本/gate；流程问题更新本文档或 AGENTS 规则
```
