from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))
SCRIPT_PATH = ROOT / "scripts" / "import_curated_glossary.py"
SPEC = importlib.util.spec_from_file_location("import_curated_glossary", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ImportCuratedGlossaryTests(unittest.TestCase):
    def test_import_updates_curated_rules(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            workbook_path = temp_path / "glossary.xlsx"
            curated_path = temp_path / "curated.json"

            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = "Glossary"
            worksheet.append(["ID", "CN", "EN", "EN2"])
            worksheet.append(["1", "报名", "Registration", "Sign Up"])
            worksheet.append(["2", "奖励", "Reward", ""])
            workbook.save(workbook_path)
            workbook.close()

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    str(workbook_path),
                    "--curated-rules",
                    str(curated_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
            payload = json.loads(curated_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["terms"]["报名"]["approved_en"], "Registration")
            self.assertEqual(payload["terms"]["报名"]["approved_en2"], "Sign Up")
            self.assertTrue(payload["terms"]["奖励"]["block_en2"])

    def test_import_accepts_clean_delivery_without_en2(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            workbook_path = temp_path / "glossary.xlsx"
            curated_path = temp_path / "curated.json"

            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = "Glossary"
            worksheet.append(["ID", "CN", "EN", "分类"])
            worksheet.append(["1", "冰霜之径", "Frostpath", "地名"])
            workbook.save(workbook_path)
            workbook.close()

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    str(workbook_path),
                    "--curated-rules",
                    str(curated_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
            payload = json.loads(curated_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["terms"]["冰霜之径"]["approved_en"], "Frostpath")
            self.assertEqual(payload["terms"]["冰霜之径"]["approved_en2"], "")
            self.assertTrue(payload["terms"]["冰霜之径"]["block_en2"])


if __name__ == "__main__":
    unittest.main()
