import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from utils.history_lookup import extract_source_queries, lookup_exact_history


def _save_workbook(path: Path, rows: list[list[object]], *, sheet_name: str = "Data") -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_name
    for row in rows:
        worksheet.append(row)
    workbook.save(path)


class HistoryLookupTests(unittest.TestCase):
    def test_extracts_unique_source_queries_in_workbook_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.xlsx"
            _save_workbook(source, [["ID", "CN", "EN"], [1, "领取奖励", ""], [2, "系统邮件", ""], [3, "领取奖励", ""]])

            self.assertEqual(extract_source_queries(source), ["领取奖励", "系统邮件"])

    def test_reads_only_requested_target_languages_and_reports_exact_miss(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history.xlsx"
            _save_workbook(
                history,
                [
                    ["ID", "CN", "EN", "FR", "DE"],
                    [1, "领取奖励", "Claim Reward", "Récupérer la récompense", "Belohnung abholen"],
                ],
            )

            result = lookup_exact_history(["领取奖励", "系统邮件"], [history], ["en", "fr"])

            self.assertEqual(result["exact_count"], 1)
            self.assertEqual(result["miss_count"], 1)
            self.assertEqual(result["results"][0]["translations"], {"en": "Claim Reward", "fr": "Récupérer la récompense"})
            self.assertNotIn("de", result["results"][0]["translations"])

    def test_accepts_short_chinese_language_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "history.xlsx"
            _save_workbook(history, [["ID", "CN", "英", "法"], [1, "系统邮件", "System Mail", "Message système"]])

            result = lookup_exact_history(["系统邮件"], [history], ["en", "fr"])

            self.assertEqual(result["exact_count"], 1)
            self.assertEqual(result["results"][0]["translations"]["en"], "System Mail")

    def test_does_not_use_fuzzy_or_punctuation_normalized_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "history.xlsx"
            _save_workbook(history, [["CN", "EN"], ["奖励已发放！", "Reward sent!"]])

            result = lookup_exact_history(["奖励已发放"], [history], ["en"])

            self.assertEqual(result["miss_count"], 1)
            self.assertEqual(result["results"][0]["translations"], {})

    def test_stops_before_opening_later_history_files_when_all_queries_resolve(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.xlsx"
            invalid_second = root / "invalid.xlsx"
            _save_workbook(first, [["CN", "EN"], ["系统邮件", "System Mail"]])
            invalid_second.write_text("not an xlsx", encoding="utf-8")

            result = lookup_exact_history(["系统邮件"], [first, invalid_second], ["en"])

            self.assertEqual(result["exact_count"], 1)
            self.assertEqual(result["scanned_history_files"], [str(first)])


if __name__ == "__main__":
    unittest.main()
