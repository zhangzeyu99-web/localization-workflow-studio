from __future__ import annotations

import json
import tempfile
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
