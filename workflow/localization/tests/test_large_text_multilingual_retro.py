from __future__ import annotations

import unittest

from utils.large_text_multilingual_retro import render_report


class LargeTextMultilingualRetroTests(unittest.TestCase):
    def test_render_report_is_readable_chinese_without_mojibake(self) -> None:
        report = render_report(
            {
                "task": "多语言包",
                "runner_timing": {
                    "total_duration": "2h 17m 26s",
                    "phases": [{"phase": "proofread", "duration": "2h 10m 51s", "seconds": 7851}],
                },
                "qa": {
                    "summary": {
                        "unique_items": 18727,
                        "translated_items": 18727,
                        "hard_blockers": 0,
                        "warnings": 1767,
                        "structural_hotfix_rows_after_deep_proofread": 3,
                        "structural_hotfix_cells_after_deep_proofread": 24,
                        "final_changed_cells_including_structural_hotfix": 6319,
                    }
                },
                "proofread": {
                    "changed_rows": 2647,
                    "changed_cells": 6295,
                    "issue_aggregates": {"by_reason_category": {"terminology": 10}},
                },
                "delivery": {
                    "exists": True,
                    "file_count": 3,
                    "files": [{"name": "QA摘要.xlsx", "bytes": 123}],
                },
                "deliver_log": {"bytes": 100, "null_bytes": 0},
                "feishu_readback": {
                    "message_id": "om_1",
                    "msg_type": "text",
                    "content_len": 80,
                    "required_missing": [],
                },
            }
        )

        self.assertIn("# 多语言包大语言包流程复盘", report)
        self.assertIn("关键证据", report)
        self.assertIn("流程问题", report)
        self.assertIn("固化优化", report)
        self.assertNotIn("????", report)
        self.assertNotIn("锛", report)

    def test_render_report_includes_executable_gate_results(self) -> None:
        report = render_report(
            {
                "task": "多语言包",
                "runner_timing": {"total_duration": "1h", "phases": []},
                "qa": {"summary": {"hard_blockers": 0, "warnings": 0}},
                "proofread": {"changed_rows": 0, "changed_cells": 0, "issue_aggregates": {}},
                "delivery": {"exists": True, "file_count": 1, "files": []},
                "deliver_log": {"bytes": 0, "null_bytes": 0},
                "feishu_readback": {"required_missing": []},
                "preflight": {
                    "exists": True,
                    "unique_items": 18727,
                    "estimated_target_cells": 149816,
                    "large_pack": True,
                    "recommended_translation_shards": 8,
                },
                "cache_lint": {"exists": True, "hard_blockers": 0, "ok_to_apply": True},
                "readback_gate": {"exists": True, "hard_blockers": 0, "readback_verified": True},
            }
        )

        self.assertIn("执行门禁结果", report)
        self.assertIn("preflight: unique=18727", report)
        self.assertIn("cache-lint: hard=0, ok_to_apply=True", report)
        self.assertIn("cache-lint: hard=0, ok_to_apply=True, status=passed", report)
        self.assertIn("readback-gate: hard=0, verified=True", report)
        self.assertIn("readback-gate: hard=0, verified=True, status=passed", report)

    def test_render_report_marks_missing_gate_results_as_skipped(self) -> None:
        report = render_report(
            {
                "task": "large pack",
                "runner_timing": {"total_duration": "1h", "phases": []},
                "qa": {"summary": {"hard_blockers": 0, "warnings": 0}},
                "proofread": {"changed_rows": 0, "changed_cells": 0, "issue_aggregates": {}},
                "delivery": {"exists": True, "file_count": 1, "files": []},
                "deliver_log": {"bytes": 0, "null_bytes": 0},
                "feishu_readback": {"required_missing": []},
            }
        )

        self.assertIn("cache-lint: status=skipped, reason=not provided, alternative_check=not provided", report)
        self.assertIn("readback-gate: status=skipped, reason=not provided, alternative_check=not provided", report)

    def test_render_report_flags_long_tasks_for_process_review(self) -> None:
        report = render_report(
            {
                "task": "large pack",
                "runner_timing": {
                    "total_seconds": 3900,
                    "total_duration": "1h 5m",
                    "phases": [{"phase": "proofread", "duration": "55m", "seconds": 3300}],
                },
                "qa": {"summary": {"hard_blockers": 0, "warnings": 0}},
                "proofread": {"changed_rows": 0, "changed_cells": 0, "issue_aggregates": {}},
                "delivery": {"exists": True, "file_count": 1, "files": []},
                "deliver_log": {"bytes": 0, "null_bytes": 0},
                "feishu_readback": {"required_missing": []},
                "cache_lint": {"exists": True, "hard_blockers": 0, "ok_to_apply": True},
                "readback_gate": {"exists": True, "hard_blockers": 0, "readback_verified": True},
            }
        )

        self.assertIn("长任务复盘触发", report)
        self.assertIn("status=triggered", report)
        self.assertIn("largest_phase=proofread:55m", report)
        self.assertIn("判断耗时是否只是任务规模导致", report)
        self.assertIn("重复出现或可机器检查的问题沉淀为测试、gate 或文档", report)


if __name__ == "__main__":
    unittest.main()
