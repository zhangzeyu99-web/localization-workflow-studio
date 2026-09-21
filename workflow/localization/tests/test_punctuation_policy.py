import json

import pytest

from utils.punctuation_policy import punctuation_issues, repair_punctuation


def test_fullwidth_range_and_english_quotes():
    assert 'fullwidth_punctuation' in punctuation_issues('Ａ１＇＂　￡', 'en')
    assert 'incompatible_punctuation' in punctuation_issues('Don’t stop. “Go!”', 'en')
    assert punctuation_issues("Don't stop. Café!", 'en') == {}


def test_language_and_explicit_project_policy():
    assert punctuation_issues('L’été, ação, mañana.', 'fr') == {}
    assert 'incompatible_punctuation' in punctuation_issues('L’été', 'fr', 'ascii')
    assert punctuation_issues('Don’t stop.', 'en', 'typographic') == {}
    assert punctuation_issues('テスト：１２', 'ja') == {}
    with pytest.raises(ValueError):
        punctuation_issues('Hello', 'en', 'unknown')


def test_repairs_only_known_characters():
    assert repair_punctuation('Don’t stop—“Café”… Ｌｖ．１２', 'en') == 'Don\'t stop - "Café"... Lv.12'
    assert repair_punctuation('wait — go', 'en') == 'wait - go'
    assert repair_punctuation('ação, mañana, café', 'en') == 'ação, mañana, café'
    assert repair_punctuation('L’été', 'fr') == 'L’été'
    from utils.text_normalize import repair_translation_surface
    assert repair_translation_surface('别怕。', 'Don’t stop！', 'en') == "Don't stop!"
    structured = '<color data="a：b’c">Don’t stop！</color> {Ｐ}'
    assert repair_translation_surface('别怕。', structured, 'en') == '<color data="a：b’c">Don\'t stop!</color> {Ｐ}'


def test_protected_structure_is_never_rewritten():
    text = '<color data="a’b">Don’t</color> {Ｐ} <@1> %s \\n'
    assert repair_punctuation(text, 'en') == '<color data="a’b">Don\'t</color> {Ｐ} <@1> %s \\n'
    payload = '{"key": "Don’t", "Ａ": "value"}'
    assert repair_punctuation(payload, 'en') == payload
    assert json.loads(payload)['key'] == 'Don’t'


def test_both_harness_and_cache_lint_block_curly_quotes(tmp_path):
    from utils.quality_harness_rules import check_row
    from utils.large_text_multilingual_gate import cache_lint
    assert 'incompatible_punctuation' in {x.check_type for x in check_row(1, '别怕。', 'Don’t be afraid.', 'en')}
    path = tmp_path / 'cache.jsonl'
    path.write_text(json.dumps({'key': '1', 'cn': '别怕。', 'translations': {'EN': 'Don’t be afraid.'}}, ensure_ascii=False) + '\n', encoding='utf-8')
    assert cache_lint(path, target_langs=['EN'])['hard_by_type']['incompatible_punctuation'] == 1


def test_readback_blocks_regression_and_project_override(tmp_path):
    from openpyxl import Workbook
    from utils.large_text_multilingual_gate import readback_gate
    from utils.quality_harness import scan_workbook
    wb = Workbook()
    wb.active.append(['ID', 'CN', 'EN'])
    wb.active.append([1, '别怕。', 'Don’t be afraid.'])
    path = tmp_path / 'final.xlsx'
    wb.save(path)
    wb.close()
    assert readback_gate(tmp_path, target_langs=['EN'])['hard_by_type']['incompatible_punctuation'] == 1
    assert readback_gate(tmp_path, target_langs=['EN'], punctuation_mode='typographic')['hard_blockers'] == 0
    assert scan_workbook(path, auto_discover_terms=False).issue_counts['incompatible_punctuation'] == 1
    assert scan_workbook(path, auto_discover_terms=False, punctuation_mode='typographic').passed
