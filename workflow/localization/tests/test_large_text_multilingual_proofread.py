from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from utils.large_text_multilingual_proofread import run_deep_proofread
from utils.large_text_multilingual_runner import build_manifest


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


class Reviewer:
    checkpoint_identity = "reviewer-v1"

    def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
        suggestions = []
        for row in rows:
            for lang in target_langs:
                if row["cn"] == "Attack" and lang in {"EN", "DE"}:
                    suggestions.append(
                        {
                            "review_key": row["review_key"],
                            "lang": lang,
                            "status": "FIX",
                            "suggested": "Attack now" if lang == "EN" else "Bad German",
                            "reason": "clarity",
                        }
                    )
                else:
                    suggestions.append(
                        {
                            "review_key": row["review_key"],
                            "lang": lang,
                            "status": "KEEP",
                            "suggested": row["translations"][lang],
                            "reason": "ok",
                        }
                    )
        return suggestions


class Auditor:
    checkpoint_identity = "auditor-v1"

    def audit_batch(self, suggestions):  # type: ignore[no-untyped-def]
        return [
            {
                "review_key": row["review_key"],
                "lang": row["lang"],
                "decision": "ACCEPT" if row["lang"] == "EN" else "REVERT",
                "final": row["suggested"],
                "reason": "meaning preserved" if row["lang"] == "EN" else "meaning narrowed",
            }
            for row in suggestions
        ]


class FailingReviewer:
    checkpoint_identity = "reviewer-v1"

    def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
        raise AssertionError("review checkpoints must be reused")


class FailingAuditor:
    checkpoint_identity = "auditor-v1"

    def audit_batch(self, suggestions):  # type: ignore[no-untyped-def]
        raise AssertionError("audit checkpoints must be reused")


class LargeTextMultilingualProofreadTests(unittest.TestCase):
    def test_sampled_mode_reviews_high_risk_rows_and_ten_percent_of_low_risk_rows(self) -> None:
        class RecordingReviewer(Reviewer):
            checkpoint_identity = "sampled-reviewer"

            def __init__(self) -> None:
                self.sources: list[str] = []

            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                self.sources.extend(str(row["cn"]) for row in rows)
                return super().review_batch(rows, target_langs)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            rows = [
                {
                    "key": str(index),
                    "cn": "高风险" * 151 if index == 0 else f"低风险 {index}",
                    "context": "ui",
                    "risk_flags": ["qa_failed_once"] if index == 1 else [],
                    "translations": {"EN": f"Text {index}"},
                }
                for index in range(21)
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="sampled",
            )
            reviewer = RecordingReviewer()

            summary = run_deep_proofread(
                Path(manifest["manifest_path"]),
                initial_cache=initial,
                reviewer=reviewer,
                auditor=Auditor(),
                batch_size=10,
            )

            self.assertEqual(summary.reviewed_rows, 4)
            self.assertEqual(len(reviewer.sources), 4)
            self.assertIn("高风险" * 151, reviewer.sources)
            self.assertIn("低风险 1", reviewer.sources)

    def test_review_retries_transient_coverage_mismatch(self) -> None:
        class FlakyReviewer(Reviewer):
            checkpoint_identity = "flaky-reviewer-v1"

            def __init__(self) -> None:
                self.calls = 0

            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                self.calls += 1
                suggestions = super().review_batch(rows, target_langs)
                if self.calls == 1:
                    suggestions[0]["review_key"] += "bad"
                return suggestions

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            rows = [{"key": "1", "cn": "Attack", "context": "ui", "translations": {"EN": "Attack"}}]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )
            reviewer = FlakyReviewer()

            summary = run_deep_proofread(
                Path(manifest["manifest_path"]),
                initial_cache=initial,
                reviewer=reviewer,
                auditor=Auditor(),
            )

            self.assertEqual(reviewer.calls, 2)
            self.assertEqual(summary.changed_cells, 1)

    def test_blank_keep_suggestion_reuses_current_translation(self) -> None:
        class BlankKeepReviewer:
            checkpoint_identity = "blank-keep-reviewer-v1"

            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                return [
                    {
                        "review_key": row["review_key"],
                        "lang": lang,
                        "status": "KEEP",
                        "suggested": "",
                        "reason": "no change needed",
                    }
                    for row in rows
                    for lang in target_langs
                ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            rows = [
                {
                    "key": "1",
                    "cn": "载具维修",
                    "context": "ui",
                    "translations": {"EN": "Vehicle Repair"},
                }
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )

            summary = run_deep_proofread(
                Path(manifest["manifest_path"]),
                initial_cache=initial,
                reviewer=BlankKeepReviewer(),
                auditor=Auditor(),
            )

            suggestions = [
                json.loads(line)
                for line in summary.suggestions_jsonl.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(suggestions[0]["suggested"], "Vehicle Repair")
            self.assertEqual(summary.changed_cells, 0)

    def test_audit_batches_use_configured_workers(self) -> None:
        class FixAllReviewer:
            checkpoint_identity = "fix-all-reviewer-v1"

            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                return [
                    {
                        "review_key": row["review_key"],
                        "lang": lang,
                        "status": "FIX",
                        "suggested": f"{row['translations'][lang]} fixed",
                        "reason": "clarity",
                    }
                    for row in rows
                    for lang in target_langs
                ]

        class ConcurrentAuditor:
            checkpoint_identity = "concurrent-auditor-v1"

            def __init__(self) -> None:
                self.active = 0
                self.max_active = 0
                self.lock = threading.Lock()

            def audit_batch(self, suggestions):  # type: ignore[no-untyped-def]
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                time.sleep(0.05)
                with self.lock:
                    self.active -= 1
                return [
                    {
                        "review_key": row["review_key"],
                        "lang": row["lang"],
                        "decision": "ACCEPT",
                        "final": row["suggested"],
                        "reason": "meaning preserved",
                    }
                    for row in suggestions
                ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            rows = [
                {
                    "key": str(index),
                    "cn": f"Text {index}",
                    "context": "ui",
                    "translations": {"EN": f"Text {index}"},
                }
                for index in range(4)
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )
            auditor = ConcurrentAuditor()

            run_deep_proofread(
                Path(manifest["manifest_path"]),
                initial_cache=initial,
                reviewer=FixAllReviewer(),
                auditor=auditor,
                batch_size=1,
                workers=2,
            )

            self.assertGreaterEqual(auditor.max_active, 2)

    def test_concurrent_proofread_owner_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            rows = [
                {
                    "key": "1",
                    "cn": "Attack",
                    "context": "ui",
                    "translations": {"EN": "Attack"},
                }
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )
            proof_dir = root / "work" / "deep_proofread"
            proof_dir.mkdir(parents=True)
            (proof_dir / "proofread.lock").write_text(
                json.dumps({"pid": os.getpid()}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "already running"):
                run_deep_proofread(
                    Path(manifest["manifest_path"]),
                    initial_cache=initial,
                    reviewer=Reviewer(),
                    auditor=Auditor(),
                )

    def test_review_batches_are_isolated_by_language(self) -> None:
        class TrackingReviewer(Reviewer):
            checkpoint_identity = "tracking-reviewer-v1"

            def __init__(self) -> None:
                self.target_lang_batches: list[list[str]] = []

            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                self.target_lang_batches.append(list(target_langs))
                return super().review_batch(rows, target_langs)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            rows = [
                {
                    "key": str(index),
                    "cn": f"Text {index}",
                    "context": "ui",
                    "translations": {"EN": f"Text {index}", "DE": f"Text {index}"},
                }
                for index in range(3)
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN", "DE"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )
            reviewer = TrackingReviewer()

            run_deep_proofread(
                Path(manifest["manifest_path"]),
                initial_cache=initial,
                reviewer=reviewer,
                auditor=Auditor(),
                batch_size=2,
                workers=2,
            )

            self.assertEqual(len(reviewer.target_lang_batches), 4)
            self.assertTrue(all(len(langs) == 1 for langs in reviewer.target_lang_batches))
            self.assertEqual(
                sorted(lang for batch in reviewer.target_lang_batches for lang in batch),
                ["DE", "DE", "EN", "EN"],
            )

    def test_review_item_checkpoints_survive_batch_size_change(self) -> None:
        class CountingReviewer(Reviewer):
            checkpoint_identity = "item-resume-reviewer-v1"

            def __init__(self) -> None:
                self.calls = 0

            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                self.calls += 1
                return super().review_batch(rows, target_langs)

        class MustReuseReviewer(Reviewer):
            checkpoint_identity = "item-resume-reviewer-v1"

            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                raise AssertionError("completed review items must be reused")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            rows = [
                {
                    "key": str(index),
                    "cn": f"Text {index}",
                    "context": "ui",
                    "translations": {"EN": f"Text {index}", "DE": f"Text {index}"},
                }
                for index in range(3)
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN", "DE"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )
            manifest_path = Path(manifest["manifest_path"])
            first = CountingReviewer()

            run_deep_proofread(
                manifest_path,
                initial_cache=initial,
                reviewer=first,
                auditor=Auditor(),
                batch_size=2,
                workers=2,
            )
            self.assertGreater(first.calls, 0)

            run_deep_proofread(
                manifest_path,
                initial_cache=initial,
                reviewer=MustReuseReviewer(),
                auditor=Auditor(),
                batch_size=1,
                workers=2,
            )

    def test_changing_reviewer_identity_does_not_reuse_old_suggestions(self) -> None:
        class OtherReviewer(Reviewer):
            checkpoint_identity = "reviewer-v2"

            def __init__(self) -> None:
                self.calls = 0

            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                self.calls += 1
                return super().review_batch(rows, target_langs)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            rows = [
                {"key": "1", "cn": "Attack", "context": "ui", "translations": {"EN": "Attack"}}
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )
            manifest_path = Path(manifest["manifest_path"])
            run_deep_proofread(
                manifest_path,
                initial_cache=initial,
                reviewer=Reviewer(),
                auditor=Auditor(),
            )
            other = OtherReviewer()

            run_deep_proofread(
                manifest_path,
                initial_cache=initial,
                reviewer=other,
                auditor=Auditor(),
            )

            self.assertEqual(other.calls, 1)

    def test_review_suggestions_require_controller_audit_before_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial_cache.jsonl"
            rows = [
                {
                    "key": "1",
                    "cn": "Attack",
                    "context": "ui",
                    "tokens": [],
                    "term_hits": [],
                    "translations": {"EN": "Attack", "DE": "Angriff"},
                },
                {
                    "key": "2",
                    "cn": "Defend",
                    "context": "ui",
                    "tokens": [],
                    "term_hits": [],
                    "translations": {"EN": "Defend", "DE": "Verteidigen"},
                },
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN", "DE"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )
            manifest_path = Path(manifest["manifest_path"])

            summary = run_deep_proofread(
                manifest_path,
                initial_cache=initial,
                reviewer=Reviewer(),
                auditor=Auditor(),
                batch_size=20,
            )

            final_rows = [
                json.loads(line)
                for line in summary.final_cache.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(final_rows[0]["translations"]["EN"], "Attack now")
            self.assertEqual(final_rows[0]["translations"]["DE"], "Angriff")
            self.assertEqual(summary.suggested_changes, 2)
            self.assertEqual(summary.reverted_changes, 1)
            self.assertEqual(summary.changed_cells, 1)
            self.assertEqual(summary.changed_rows, 1)
            saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_manifest["phase_status"]["subagent_review"], "done")
            self.assertEqual(saved_manifest["phase_status"]["controller_merge"], "done")

            resumed = run_deep_proofread(
                manifest_path,
                initial_cache=initial,
                reviewer=FailingReviewer(),
                auditor=FailingAuditor(),
                batch_size=20,
            )
            self.assertEqual(resumed.changed_cells, 1)

    def test_review_rejects_incomplete_suggestion_contract(self) -> None:
        class BadReviewer:
            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                return []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            rows = [
                {"key": "1", "cn": "Attack", "context": "ui", "translations": {"EN": "Attack"}}
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )

            with self.assertRaisesRegex(ValueError, "review coverage"):
                run_deep_proofread(
                    Path(manifest["manifest_path"]),
                    initial_cache=initial,
                    reviewer=BadReviewer(),
                    auditor=Auditor(),
                )


if __name__ == "__main__":
    unittest.main()
