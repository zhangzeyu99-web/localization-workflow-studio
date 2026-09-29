# 工作流同步说明

本目录是翻译、QA、回填与交付的运行时同步副本，维护源为 `D:\project\localization-workflow-project`。业务逻辑只在维护源修改；工作台侧的同步规则维护于 `scripts/sync_workflow_sources.py`。

- 源仓库修改后只检查受影响行为，再运行 `python scripts/sync_workflow_sources.py localization`。
- 测试在原维护源保留；`tests/` 不进入同步范围。2026-09-29 按用户要求移除工作台内已有测试副本，后续同步不再带回。
- 脚本只直接读回本次复制的文件，不生成 SHA 或全目录哈希清单。
- 同步影响工作台运行入口时，检查工作台对应的精简集成用例；不重复运行上下游整套测试。
- 具体排除项以 `TARGETS` 配置为准；产品所需 scripts、utils、templates、fixtures 保留，`SYNC.md` 在工作台侧维护。
