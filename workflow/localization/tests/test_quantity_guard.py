import json
import tempfile
import unittest
from pathlib import Path

from utils.large_text_multilingual_gate import cache_lint
from utils.quality_harness_rules import DEFAULT_HARD_ISSUES, check_row
from utils.quantity_guard import quantity_issues


class QuantityGuardTests(unittest.TestCase):
    def test_fixture_gate_and_harness_parity(self):
        fixture = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/quality_regression.json').read_text(encoding='utf-8'))
        for case in fixture['quantity_guard_cases']:
            with self.subTest(case['name']):
                expected = set(case['expected'])
                actual = {kind for kind, _ in quantity_issues(case['source'], case['target'], case['lang'])}
                self.assertEqual(actual, expected)
                row_issues = {x.check_type for x in check_row(1, case['source'], case['target'], case['lang']) if x.check_type.startswith('quantity_')}
                self.assertEqual(row_issues, expected)
                self.assertLessEqual(expected, DEFAULT_HARD_ISSUES)
                with tempfile.TemporaryDirectory() as tmp:
                    cache = Path(tmp) / 'cache.jsonl'
                    cache.write_text(json.dumps({'key': case['name'], 'cn': case['source'], 'translations': {case['lang']: case['target']}}, ensure_ascii=False) + '\n', encoding='utf-8')
                    result = cache_lint(cache, target_langs=[case['lang']])
                    self.assertEqual({x['type'] for x in result['issues'] if x['type'].startswith('quantity_')}, expected)


if __name__ == '__main__':
    unittest.main()
