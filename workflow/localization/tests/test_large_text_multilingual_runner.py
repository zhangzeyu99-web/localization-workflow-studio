from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from utils.large_text_multilingual_runner import (
    build_manifest,
    load_sanitized_relay_config,
    record_api_smoke,
    workflow_status,
)


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


class LargeTextMultilingualRunnerTests(unittest.TestCase):
    def test_load_sanitized_relay_config_keeps_host_and_drops_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            relay = Path(tmp) / "relay-api-config.json"
            relay.write_text(
                json.dumps(
                    {
                        "base_url": "https://aicode-api3.gz4399.com/api",
                        "model": "gpt-5.5",
                        "api_key": "secret-token",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            config = load_sanitized_relay_config(relay)

            self.assertEqual(config["source"], str(relay))
            self.assertEqual(config["base_url_host"], "aicode-api3.gz4399.com")
            self.assertEqual(config["base_url_path"], "/api")
            self.assertEqual(config["model"], "gpt-5.5")
            self.assertNotIn("api_key", config)

    def test_build_manifest_defaults_to_api_translation_without_subagent_full_proofread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            source_rows = root / "source_rows.jsonl"
            relay = root / "relay-api-config.json"
            write_jsonl(items, [{"key": str(i), "cn": "短文本"} for i in range(3)])
            write_jsonl(source_rows, [{"key": str(i), "row": i} for i in range(3)])
            relay.write_text(
                json.dumps({"base_url": "https://aicode-api3.gz4399.com/api", "model": "gpt-5.5", "api_key": "secret"}),
                encoding="utf-8",
            )

            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=source_rows,
                target_langs=["DE", "FR", "ES", "PT", "RU"],
                workbook_count=2,
                relay_config=relay,
                proofread_mode="basic",
            )

            self.assertEqual(manifest["workflow"], "large_text_multilingual_v1")
            self.assertEqual(manifest["status"], "prepared")
            self.assertIs(manifest["preflight"]["large_pack"], True)
            self.assertEqual(manifest["api_strategy"]["mode"], "relay_openai_compatible")
            self.assertEqual(manifest["api_strategy"]["model"], "gpt-5.5")
            self.assertNotIn("api_key", json.dumps(manifest, ensure_ascii=False))
            self.assertIs(manifest["subagent_strategy"]["enabled"], False)
            self.assertEqual(manifest["subagent_strategy"]["mode"], "not_triggered")
            self.assertEqual(
                manifest["critical_path"],
                [
                    "preflight",
                    "api_smoke",
                    "api_translate",
                    "incremental_cache_lint",
                    "apply_dry_run",
                    "write_outputs",
                    "readback_gate",
                    "retro_metrics",
                ],
            )
            self.assertTrue(Path(manifest["manifest_path"]).exists())

    def test_build_manifest_enables_subagent_only_for_explicit_deep_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            write_jsonl(items, [{"key": str(i), "cn": "长" * 301 if i == 0 else "短文本"} for i in range(10)])

            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["DE", "FR", "ES", "PT", "RU", "IT", "TR", "TH"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="sampled",
            )

            strategy = manifest["subagent_strategy"]
            self.assertIs(strategy["enabled"], True)
            self.assertEqual(strategy["mode"], "sampled")
            self.assertEqual(strategy["write_permission"], "forbidden")
            self.assertEqual(strategy["output_contract"], "jsonl_review_suggestions_only")
            self.assertGreaterEqual(strategy["parallel_agents"], 2)
            self.assertIn("long_text", strategy["risk_flags"])

    def test_record_api_smoke_updates_status_without_storing_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            write_jsonl(items, [{"key": "1", "cn": "短文本"}])
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["DE"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="basic",
            )

            updated = record_api_smoke(
                Path(manifest["manifest_path"]),
                ok=True,
                latency_ms=1200,
                schema_ok=True,
                model_returned="gpt-5.5",
                endpoint_suffix="/v1/chat/completions",
                error="",
            )

            self.assertEqual(updated["status"], "api_smoke_passed")
            self.assertIs(updated["api_smoke"]["ok"], True)
            self.assertEqual(workflow_status(updated)["next_phase"], "api_translate")
            self.assertNotIn("api_key", json.dumps(updated, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
