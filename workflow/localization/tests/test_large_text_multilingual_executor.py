from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from utils.large_text_multilingual_executor import _partition_requests, translate_manifest
from utils.large_text_multilingual_runner import build_manifest


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


class FakeClient:
    checkpoint_identity = "fake-translator"

    def __init__(self) -> None:
        self.calls: list[list[dict[str, object]]] = []

    def translate_batch(
        self,
        rows: list[dict[str, object]],
        target_langs: list[str],
    ) -> list[dict[str, object]]:
        self.calls.append(rows)
        return [
            {
                "request_key": row["request_key"],
                "translations": {
                    lang: f"{lang}:{row['cn']}" for lang in target_langs
                },
            }
            for row in rows
        ]


class FailingClient:
    checkpoint_identity = "fake-translator"

    def translate_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
        raise AssertionError("completed checkpoints must be reused")


class SplitClient(FakeClient):
    def translate_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
        self.calls.append(rows)
        if len(rows) > 1:
            raise RuntimeError("provider rejects large batch")
        return [
            {
                "request_key": rows[0]["request_key"],
                "translations": {
                    lang: f"{lang}:{rows[0]['cn']}" for lang in target_langs
                },
            }
        ]


class IdentifiedClient(FakeClient):
    def __init__(self, identity: str) -> None:
        super().__init__()
        self.checkpoint_identity = identity


class LargeTextMultilingualExecutorTests(unittest.TestCase):
    def test_partition_respects_row_and_character_limits(self) -> None:
        rows = [
            {"request_key": str(index), "cn": "x" * 60}
            for index in range(5)
        ]
        batches = _partition_requests(rows, max_rows=4, max_chars=180)

        self.assertEqual([len(batch) for batch in batches], [2, 2, 1])

    def test_translate_deduplicates_and_resumes_without_persisting_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            rows = [
                {"key": "1", "cn": "Attack", "context": "ui", "term_hits": []},
                {"key": "2", "cn": "Attack", "context": "ui", "term_hits": []},
                {"key": "3", "cn": "Defend", "context": "language", "term_hits": []},
            ]
            write_jsonl(items, rows)
            relay = root / "relay.json"
            relay.write_text(
                json.dumps(
                    {
                        "base_url": "https://relay.example/v1",
                        "model": "test-model",
                        "api_key": "top-secret",
                    }
                ),
                encoding="utf-8",
            )
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN", "IDN"],
                workbook_count=1,
                relay_config=relay,
                proofread_mode="basic",
            )

            client = FakeClient()
            first = translate_manifest(
                Path(manifest["manifest_path"]),
                relay_config=relay,
                client=client,
                batch_size=20,
            )

            self.assertEqual(first.source_rows, 3)
            self.assertEqual(first.unique_api_rows, 2)
            self.assertEqual(sum(len(call) for call in client.calls), 2)
            cache_rows = [
                json.loads(line)
                for line in first.cache_jsonl.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(cache_rows), 3)
            self.assertEqual(cache_rows[0]["translations"], cache_rows[1]["translations"])

            second = translate_manifest(
                Path(manifest["manifest_path"]),
                relay_config=relay,
                client=FailingClient(),
                batch_size=20,
            )
            self.assertEqual(second.reused_batches, 1)
            manifest_text = Path(manifest["manifest_path"]).read_text(encoding="utf-8")
            metrics_text = second.metrics_json.read_text(encoding="utf-8")
            self.assertNotIn("top-secret", manifest_text)
            self.assertNotIn("top-secret", metrics_text)
            self.assertEqual(json.loads(manifest_text)["phase_status"]["api_translate"], "done")

    def test_translate_rejects_missing_language_or_unknown_request_key(self) -> None:
        class InvalidClient:
            def translate_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                return [
                    {
                        "request_key": "unknown",
                        "translations": {"EN": "Only one language"},
                    }
                ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            write_jsonl(items, [{"key": "1", "cn": "Attack", "context": "ui"}])
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN", "DE"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="basic",
            )

            with self.assertRaisesRegex(ValueError, "response keys"):
                translate_manifest(
                    Path(manifest["manifest_path"]),
                    relay_config=None,
                    client=InvalidClient(),
                )

    def test_translate_request_uses_english_source_and_reference_in_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            rows = [
                {
                    "key": "1",
                    "cn": "技能",
                    "translation_source": "Flame Strike",
                    "source_mode": "en",
                    "reference_en": "Flame Strike",
                    "reference_en_status": "usable",
                    "context": "ui",
                    "term_hits": [],
                },
                {
                    "key": "2",
                    "cn": "技能",
                    "translation_source": "Blaze Slash",
                    "source_mode": "en",
                    "reference_en": "Blaze Slash",
                    "reference_en_status": "usable",
                    "context": "ui",
                    "term_hits": [],
                },
            ]
            write_jsonl(items, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["FR"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="basic",
                source_mode="en",
            )
            client = FakeClient()

            result = translate_manifest(
                Path(manifest["manifest_path"]),
                relay_config=None,
                client=client,
                batch_size=20,
            )

            self.assertEqual(result.unique_api_rows, 2)
            request_rows = [row for call in client.calls for row in call]
            self.assertEqual(
                {row["translation_source"] for row in request_rows},
                {"Flame Strike", "Blaze Slash"},
            )
            self.assertTrue(all(row["source_mode"] == "en" for row in request_rows))

    def test_checkpoint_scope_changes_with_target_languages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            write_jsonl(items, [{"key": "1", "cn": "Attack", "context": "ui"}])
            first_manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="basic",
            )
            translate_manifest(
                Path(first_manifest["manifest_path"]),
                relay_config=None,
                client=FakeClient(),
            )
            second_manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN", "DE"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="basic",
            )
            client = FakeClient()

            result = translate_manifest(
                Path(second_manifest["manifest_path"]),
                relay_config=None,
                client=client,
            )

            self.assertEqual(result.reused_batches, 0)
            self.assertEqual(sum(len(call) for call in client.calls), 1)

    def test_failed_large_batch_is_split_and_child_checkpoints_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            write_jsonl(
                items,
                [
                    {"key": str(index), "cn": f"Text {index}", "context": "ui"}
                    for index in range(3)
                ],
            )
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="basic",
            )
            manifest_path = Path(manifest["manifest_path"])
            client = SplitClient()

            first = translate_manifest(
                manifest_path,
                relay_config=None,
                client=client,
                batch_size=20,
                max_attempts=1,
            )
            second = translate_manifest(
                manifest_path,
                relay_config=None,
                client=FailingClient(),
                batch_size=20,
                max_attempts=1,
            )

            self.assertEqual(first.source_rows, 3)
            self.assertEqual(second.reused_batches, 1)

    def test_checkpoint_scope_changes_with_provider_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            write_jsonl(items, [{"key": "1", "cn": "Attack", "context": "ui"}])
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="basic",
            )
            manifest_path = Path(manifest["manifest_path"])
            translate_manifest(
                manifest_path,
                relay_config=None,
                client=IdentifiedClient("provider-a"),
            )
            second_client = IdentifiedClient("provider-b")

            result = translate_manifest(
                manifest_path,
                relay_config=None,
                client=second_client,
            )

            self.assertEqual(result.reused_batches, 0)
            self.assertEqual(sum(len(call) for call in second_client.calls), 1)


if __name__ == "__main__":
    unittest.main()
