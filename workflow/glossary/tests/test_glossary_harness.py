from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = ROOT / "scripts" / "run_glossary_harness.py"
SPEC = importlib.util.spec_from_file_location("glossary_harness", HARNESS_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class HarnessTests(unittest.TestCase):
    def test_evaluate_fixture_reports_pass(self):
        fixture_path = ROOT / "fixtures" / "core_regression.json"
        report = MODULE.evaluate_fixture(fixture_path)
        self.assertTrue(report["pass"])
        self.assertEqual(report["exact_match_count"], 3)
        self.assertEqual(report["missing_terms"], [])
        self.assertEqual(report["mismatched_terms"], [])

    def test_harness_cli_writes_report(self):
        fixture_path = ROOT / "fixtures" / "core_regression.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "report.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(HARNESS_PATH),
                    str(fixture_path),
                    "--report-output",
                    str(report_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["all_passed"])
            self.assertEqual(len(payload["reports"]), 1)


if __name__ == "__main__":
    unittest.main()
