from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "export_glossary_candidates.py"


def write_book(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "翻译需求"
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def test_candidate_export_merges_evidence_and_applies_review(tmp_path: Path) -> None:
    source = tmp_path / "batch.xlsx"
    glossary = tmp_path / "glossary.xlsx"
    review = tmp_path / "review.json"
    output = tmp_path / "candidates.json"
    write_book(
        source,
        ["ID", "CN", "EN", "FR"],
        [
            [1, "夜巡秘境", "Night Patrol Realm", ""],
            [2, "夜巡秘境", "", "Royaume de patrouille nocturne"],
            [3, "竞技场", "Arena", "Arène"],
            [4, "已领取", "Claimed", "Reçu"],
            [5, "本次活动结束后奖励将通过邮件发送。", "", ""],
            [6, "击败“荒魂将军”可获得奖励。", "", ""],
        ],
    )
    write_book(glossary, ["ID", "CN", "EN", "FR", "分类"], [[1, "竞技场", "Arena", "", "活动"]])
    review.write_text(
        json.dumps(
            {
                "decisions": {
                    "夜巡秘境": {"decision": "include", "category": "副本"},
                    "已领取": {"decision": "reject", "category": "UI", "reason": "状态提示"},
                },
                "additional_candidates": [
                    {
                        "cn": "荒魂将军",
                        "decision": "include",
                        "category": "怪物",
                        "evidence_contains": "荒魂将军",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(source),
            "--existing-glossary",
            str(glossary),
            "--target-langs",
            "EN,FR",
            "--review-file",
            str(review),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["target_languages"] == ["EN", "FR"]
    assert payload["summary"]["source_rows"] == 6
    assert payload["summary"]["unique_source_texts"] == 5
    rows = {row["cn"]: row for row in payload["candidates"]}
    assert rows["夜巡秘境"]["decision"] == "include"
    assert rows["夜巡秘境"]["translations"] == {
        "EN": "Night Patrol Realm",
        "FR": "Royaume de patrouille nocturne",
    }
    assert len(rows["夜巡秘境"]["evidence"]) == 2
    assert rows["竞技场"]["decision"] == "reject"
    assert rows["竞技场"]["reason"] == "existing_glossary"
    assert rows["已领取"]["decision"] == "reject"
    assert rows["荒魂将军"]["decision"] == "include"
    assert rows["荒魂将军"]["evidence"][0]["row"] == 7
    assert payload["summary"]["existing_incomplete"] == 1
    assert payload["existing_incomplete"] == [
        {
            "cn": "竞技场",
            "missing_languages": ["FR"],
            "translations": {"EN": "Arena", "FR": ""},
            "evidence": rows["竞技场"]["evidence"],
        }
    ]


def test_candidate_export_requires_all_stable_arguments(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode != 0
    assert "--input" in result.stderr
    assert "--existing-glossary" in result.stderr
    assert "--target-langs" in result.stderr
    assert "--output" in result.stderr


def test_review_cannot_reinclude_existing_terms(tmp_path: Path) -> None:
    from glossary_extraction.candidate_export import export_candidates

    source, glossary, review, output = [tmp_path / name for name in
                                       ('source.xlsx', 'terms.xlsx', 'review.json', 'out.json')]
    write_book(source, ['ID', 'CN', 'EN'], [[1, '神器', ''], [2, '升级神兵可提高伤害', '']])
    write_book(glossary, ['ID', 'CN', 'EN'], [[1, '神器', 'Artifact'], [2, '神兵', 'Weapon']])
    review.write_text(json.dumps({
        'decisions': {'神器': {'decision': 'include', 'category': '装备'}},
        'additional_candidates': [{'cn': '神兵', 'decision': 'include', 'category': '装备',
                                   'translations': {'EN': 'Wrong'}}],
    }), encoding='utf-8')
    result = export_candidates([source], glossary, ['EN'], output, review)
    rows = {row['cn']: row for row in result['candidates']}
    for cn, expected in [('神器', 'Artifact'), ('神兵', 'Weapon')]:
        assert rows[cn]['decision'] == 'reject'
        assert rows[cn]['reason'] == 'existing_glossary'
        assert rows[cn]['translations']['EN'] == expected


def test_bracketed_skill_names_are_candidates_not_silently_skipped() -> None:
    from glossary_extraction.candidate_export import candidate_terms

    names = candidate_terms('替换武器<@1>:技能【幽谷银镰】变大,伤害+<@2>%')
    assert '幽谷银镰' in names
    assert candidate_terms('技能【星辉审判】弹道+<@2>,再次触发【星辉审判】').count('星辉审判') == 1
    assert '伤害+<@2>%' not in candidate_terms('提升【伤害+<@2>%】')
    assert '星铸金核' in candidate_terms('消耗【<color=#FF<@1>>星铸金核</color>】')
    assert '>星铸金核' not in candidate_terms('消耗【<color=#FF<@1>>星铸金核</color>】')


def test_category_and_common_action_do_not_auto_approve_permanent_terms() -> None:
    from glossary_extraction.candidate_export import auto_decision

    for cn in ('购买', '强化', '公会', '夜巡秘境'):
        assert auto_decision(cn, set())[0] == 'needs_context'
    assert auto_decision('已领取', set())[0] == 'reject'
    assert auto_decision('购买', {'购买'})[2] == 'existing_glossary'
