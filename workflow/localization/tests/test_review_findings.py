import json
import tempfile
import unittest
from pathlib import Path

from utils.large_text_multilingual_gate import cache_lint
from utils.large_text_multilingual_proofread import _validate_suggestions
from utils.review_findings import unresolved_review_detail


class ReviewFindingTests(unittest.TestCase):
    def test_declared_findings_block_keep_and_fix(self):
        for status in ['KEEP', 'FIX']:
            for fields in [{'unresolved_issues': ['Duration is missing']}, {'reason': '既有译文缺时长，提交主控QA'}, {'unresolved_issues': 'none'}]:
                row = dict(review_key='r1', lang='PT', status=status, suggested='Acelerar Cura', **fields)
                with self.subTest(status=status, fields=fields):
                    self.assertTrue(unresolved_review_detail(row))
                    with self.assertRaises(ValueError):
                        _validate_suggestions([{'review_key': 'r1', 'translations': {'PT': 'Acelerar Cura'}}], [row], ['PT'])
                    with tempfile.TemporaryDirectory() as tmp:
                        p = Path(tmp) / 'cache.jsonl'
                        p.write_text(json.dumps(dict(key='r1', cn='治疗加速', translations={'PT': 'Acelerar Cura'}, **fields)), encoding='utf-8')
                        result = cache_lint(p, target_langs=['PT'])
                        self.assertIn('unresolved_review_finding', result['hard_by_type'])

    def test_resolved_record_and_ordinary_context_uncertainty(self):
        for row in [{'unresolved_issues': [], 'reason': '已补回时长并复核'}, {'reason': '性别语境不明确，保留原称谓'}]:
            self.assertEqual(unresolved_review_detail(row), '')


if __name__ == '__main__':
    unittest.main()
