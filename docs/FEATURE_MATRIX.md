# 核心测试范围

精简后的套件保留下列代表场景。普通改动只运行受影响的测试文件或 `-k` 场景；CI 与发布运行精简核心集合。新增测试应捕获具体用户故障，优先替换重复场景，不因本表缺项自动扩展覆盖。

| 功能 | 后端入口 | 前端入口 |
| --- | --- | --- |
| 正式翻译、QA、交付和公告 | `backend/tests/test_workflow_e2e.py` | `frontend/e2e/studio-ui-flow.spec.ts` |
| 多语言交付、任务隔离和非目标列保护 | `backend/tests/test_multilingual_delivery.py`、`backend/tests/test_multilingual_orchestration.py` | `frontend/e2e/studio-ui-flow.spec.ts` |
| FIFO、双 lane、取消和重启恢复 | `backend/tests/test_job_queue.py`、`backend/tests/test_integrated_queue_lifecycle.py` | 不再保留专用队列 UI 变体 |
| 任务终态、取消后停止 QA、快速任务不写归档 | `backend/tests/test_translation_task_lifecycle.py`、`backend/tests/test_translation_qa_cancellation.py`、`backend/tests/test_quick_task_lifecycle.py` | `frontend/e2e/studio-ui-flow.spec.ts` |
| 归档导入、指定语言范围、冲突阻断和回滚 | `backend/tests/test_archive_import_contracts.py`、`backend/tests/test_translation_archive_batches.py` | `frontend/e2e/archive-import-flow.spec.ts` |
| 历史交付文件仍可下载 | 翻译与交付核心入口 | `frontend/e2e/delivery-history.spec.ts` |
| 登录、无效凭据、登出及测试数据隔离 | `backend/tests/test_auth.py`、`backend/tests/test_test_data_safety.py` | `frontend/e2e/runtime-profile-smoke.spec.ts` |

大文本细项、供应商故障变体、完整权限矩阵、逐句审校、部署/打包单测，以及大量 UI 状态和布局变体已移除。核心集合通过不表示这些范围获得了等价自动覆盖；发布与部署仍按 `STABILITY_TEST_LIST.md` 验收。

## 入口

```powershell
python -m pytest backend/tests -q
npm --prefix frontend run e2e
```

pytest 与 Playwright 各用隔离临时数据；不要把浏览器入口指向真实业务服务。维护源测试只在对应源仓运行，Studio 不再同步测试副本。
