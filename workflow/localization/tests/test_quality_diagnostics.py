import unittest
import json
from pathlib import Path

from utils.quality_diagnostics import diagnose_scope


class QualityDiagnosticsTests(unittest.TestCase):
    def test_fixture_contract(self):
        cases = json.loads((Path(__file__).resolve().parents[1]/'fixtures/quality_regression.json').read_text(encoding='utf-8'))['diagnostic_regression_cases']
        for case in cases:
            report = diagnose_scope([self.row()], ['FR'], [('s|1','FR')], sampling=case['sampling'], unresolved=case['unresolved'])
            self.assertEqual(report['full_semantic_review'], case['full_semantic_review'])
            self.assertEqual(report['resolved_reviewed_cells'], case['resolved_reviewed_cells'])
            self.assertIsNone(report['overall_quality_score'])

    def row(self, key='s|1', ident='a', value='Open'):
        return {'key': key, 'id': ident, 'sheet': 's', 'file': 'book',
                'translation_source': value, 'translations': {'FR': value}}

    def test_purposive_sample_is_not_overall_score(self):
        report = diagnose_scope([self.row()], ['FR'], [('s|1', 'FR')], sampling='purposive')
        self.assertIsNone(report['overall_quality_score'])
        self.assertFalse(report['full_semantic_review'])
        self.assertEqual(report['unique_reviewed_cells'], 1)

    def test_unknown_not_pass(self):
        report = diagnose_scope([self.row()], ['FR'], [('s|1', 'FR')],
                                unresolved=[('s|1', 'FR')], sampling='census')
        self.assertFalse(report['release_ready'])
        self.assertEqual(report['resolved_reviewed_cells'], 0)

    def test_physical_keys_do_not_hide_conflicting_resource_ids(self):
        rows = [self.row(), self.row('s|2', value='Close')]
        report = diagnose_scope(rows, ['FR'], [])
        self.assertEqual(len(report['conflicting_id_groups']), 1)
        self.assertFalse(report['release_ready'])

    def test_separate_sheets_are_separate_namespaces(self):
        b = self.row('t|2'); b['sheet'] = 't'
        self.assertFalse(diagnose_scope([self.row(), b], ['FR'], [])['conflicting_id_groups'])

    def test_duplicate_coverage_cannot_inflate_sample(self):
        report = diagnose_scope([self.row()], ['FR'], [('s|1','FR')]*3)
        self.assertEqual(report['unique_reviewed_cells'], 1)

    def test_out_of_scope_coverage_fails(self):
        with self.assertRaises(ValueError):
            diagnose_scope([self.row()], ['FR'], [('s|2','FR')])

    def test_duplicate_row_key_fails(self):
        with self.assertRaises(ValueError):
            diagnose_scope([self.row(), self.row()], ['FR'], [])

    def test_unreviewed_unknown_still_blocks(self):
        report = diagnose_scope([self.row()], ['FR'], [], unresolved=[('s|1','FR')])
        self.assertEqual(report['unresolved_cells'], 1)

    def test_quality_score_never_inferred_from_coverage_alone(self):
        report = diagnose_scope([self.row()], ['FR'], [('s|1','FR')], sampling='census')
        self.assertTrue(report['full_semantic_review'])
        self.assertIsNone(report['overall_quality_score'])
        self.assertFalse(report['release_ready'])


if __name__ == '__main__':
    unittest.main()
