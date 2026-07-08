# 功能保护矩阵

本表用于优化和拆分时防止前后端功能缺失。每次重构只要触碰对应区域，就必须跑绑定测试；没有列入本表的新增能力，需要先补最小保护测试。

| 功能 | 后端保护 | 前端保护 |
| --- | --- | --- |
| 项目创建、刷新、删除 | `test_duplicate_project_name_returns_existing_project`、`test_delete_project_removes_project_records_and_files` | `project list refreshes after an external project is created`、`new project modal shows API failure instead of silently staying stuck` |
| 文件上传与大文件分片 | `test_upload_streaming_rejects_oversized_file_and_sanitizes_name`、`test_chunked_upload_assembles_file_and_creates_artifact` | `user can complete the EN localization workflow from project tabs` |
| 完整翻译流程 | `test_fake_provider_runs_english_workflow_end_to_end`、`test_translation_batch_retry_persists_after_transient_failure` | `user can complete the EN localization workflow from project tabs` |
| 快速任务上传 / 粘贴 | `test_quick_task_artifacts_detect_languages_and_stay_temporary`、`test_quick_task_can_translate_txt_and_deliver_same_format`、`test_quick_txt_translation_workpack_uses_terms_and_project_archive` | `quick task creates a project-scoped QA run without nine step workflow`、`quick task translates pasted text and shows copyable result in step three` |
| 术语库与归档译文 | `test_glossary_and_translation_archive_are_language_scoped`、`test_translation_archive_import_edit_and_export`、`test_glossary_preview_import_and_export` | `project tabs show multilingual wide glossary and archive assets`、`wide glossary and archive support strong search, display languages, and 100 row paging` |
| 直接 QA、手动修复、模型修复 | `test_existing_translation_workbook_can_run_qa_without_translation_workpack`、`test_manual_fix_creates_fixed_workbook_reruns_qa_and_updates_project_harness`、`test_model_fix_applies_provider_suggestions_and_reruns_qa` | `user can upload an existing translated workbook and run QA directly`、`user can repair failed QA rows and rerun QA from the web UI` |
| 公告流程 | `test_announcement_task_txt_multilingual_flow_uses_archive_priority_and_delivers`、`test_announcement_lookup_uses_glossary_and_qa_passed_archive` | `project announcement workflow extracts terms with AI supplement and prepares delivery` |
| 公告术语 AI 补充（先确定性反查，AI 只做证据受限的漏词复查；未配置 API 时降级为检查包+报告，不调用模型；只有证据充分且有译文的中高置信术语进入主表，其余仅留在报告） | `test_announcement_ai_supplement_falls_back_to_packet_without_provider_key`、`test_announcement_task_extract_terms_accepts_ai_supplement_response`、`test_announcement_task_extract_terms_calls_provider_for_ai_supplement`、`test_announcement_ai_supplement_does_not_readd_low_value_terms` | `project announcement workflow extracts terms with AI supplement and prepares delivery` |
| 交付包 | `test_delivery_package_contains_only_task_outputs`、`test_delivery_filename_sanitizes_invalid_project_name_without_double_spaces`、`test_merged_delivery_combines_passed_language_outputs` | `delivery empty state routes to next actions`、`user can explicitly skip QA and archive an existing translated language table` |
| 设置与供应商保护 | `test_formal_translation_is_blocked_without_configured_api_key`、`test_openai_provider_does_not_fallback_to_chat_completions` | `real project formal translation is blocked without configured API credential`、`announcement AI translation shows API reminder when provider is not configured` |
| 多语言队列 | `test_start_multilingual_translation_creates_missing_child_runs`、`test_multilingual_qa_skips_languages_without_translated_input` | `new translation task exposes the full supported language set` |
| 大文本产品化门禁（大语言表/多语言包在 Step 7 显示 preflight，翻译写入前跑 cache-lint，交付时跑 readback gate，并生成 retro artifact） | `backend/tests/test_large_text_productization.py`、`backend/tests/test_long_text_orchestration.py` | `frontend/e2e/studio-ui-flow.spec.ts`（`interrupted translation run resumes instead of creating a new run` 断言 `large-text-panel`） |
| 多人并发（项目级锁 `long_text:{project_id}`、全局并发上限 `max_concurrent_ai_jobs`、`GET /api/system/active-jobs`、共享限流器、settings 快照、删除防护） | `backend/tests/test_concurrency_lease.py`、`backend/tests/test_shared_rate_limiter.py`、`backend/tests/test_shared_resource_protection.py`、`scripts/concurrency_smoke.py` | `frontend/e2e/studio-ui-flow.spec.ts`（`active jobs badge and panel show the running project name and task type`、`starting a second task on a busy project shows a queue hint that opens the active jobs panel`） |

## 重构默认门禁

- 后端基础：`python -m ruff check backend/app backend/tests scripts --select E9,F`
- Python 编译：`python -m compileall -q backend workflow scripts`
- 前端构建：`npm --prefix frontend run build`
- 后端 workflow：`python -m pytest backend/tests/test_workflow_e2e.py -q`
- 前端流程：`npm --prefix frontend run e2e -- --workers=1`

`frontend-v2/` 是未跟踪原型目录，不是主应用入口；优化主线不得直接替换 `frontend/`。
