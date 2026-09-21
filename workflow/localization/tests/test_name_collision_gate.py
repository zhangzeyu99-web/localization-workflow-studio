import json

import pytest

from utils.name_collision_gate import audit_changes, main, normalized_name, scan_names


def name(id="a", cn="风刃", text="Wind Blade", lang="EN", scope="game:skills"):
    return dict(scope=scope, id=id, cn=cn, text=text, lang=lang)


def change(id="a", before="Old", after="New", **kwargs):
    row = name(id=id, **kwargs)
    row.pop("text")
    return dict(row, before=before, after=after)


def test_collision_normalizes_presentation_but_keeps_different_languages_scopes_and_digits():
    rows = [name(), name("b", "冰刃", "WIND-BLADE"), name("c", "水刃", "Wind Blade 2"),
            name("d", "土刃", "Wind Blade", lang="DE"), name("e", "火刃", scope="other:skills")]
    report = scan_names(rows)
    assert report["collision_groups"] == report["hard_blockers"] == 1
    assert normalized_name("Éclair") != normalized_name("Eclair")


def test_repeated_id_or_same_source_names_are_not_collisions():
    assert scan_names([name(), name(), name("b")])["ok"]


def test_conflicting_id_is_blocked():
    assert scan_names([name(), name(cn="冰刃")])["issues"][0]["type"] == "definition_id_conflict"


def test_approval_is_exact_and_cannot_override_explicit_split_requirement():
    rows = [name(), name("b", "冰刃")]
    fp = scan_names(rows)["collisions"][0]["fingerprint"]
    approval = [dict(fingerprint=fp, decision="allow_shared", reason="Reviewed contextual equivalence")]
    assert scan_names(rows, approvals=approval)["ok"]
    assert not scan_names(rows, approvals=approval, require_distinct=True)["ok"]
    assert not scan_names([name(), name("c", "冰刃")], approvals=approval)["ok"]
    assert not scan_names(rows, approvals=[dict(fingerprint=fp, decision="allow_shared")])["ok"]


def test_glossary_sync_requires_actual_matching_name():
    assert scan_names([name()], glossary=[name("term1")])["ok"]
    assert not scan_names([name()], glossary=[])["ok"]
    assert not scan_names([name()], glossary=[name("term1", text="Old")])["ok"]
    assert not scan_names([name()], glossary=[name("t1"), name("t2", text="Old")])["ok"]


@pytest.mark.parametrize("rows", [[], [name(text="")], [name(text="---")], [name(id="")]])
def test_empty_input_cannot_pass(rows):
    with pytest.raises(ValueError):
        scan_names(rows)


def test_cumulative_delivery_catches_earlier_round_omission():
    first, second = [change()], [change("b")]
    assert audit_changes([first, second], [*first, *second])["ok"]
    assert audit_changes([first, second], second)["issues"][0]["type"] == "missing_delivery_cell"


def test_chain_keeps_earliest_before_latest_after_and_allows_same_round_format_duplicate():
    a, b = change(), change(before="New", after="Final")
    assert audit_changes([[a, a], [b]], [change(after="Final")])["ok"]
    assert not audit_changes([[a], [b]], [b])["ok"]
    assert audit_changes([[a], [change(before="New", after="Old")]], [])["ok"]


@pytest.mark.parametrize("second", [change(before="Unexpected"), change(before="New", cn="冰刃")])
def test_broken_chain_or_source_drift_blocks(second):
    assert not audit_changes([[change()], [second]], [change()])["ok"]


def test_extra_or_duplicate_delivery_blocks():
    assert not audit_changes([[change()]], [change(), change("b")])["ok"]
    assert not audit_changes([[change()]], [change(), change()])["ok"]


def test_new_translation_from_blank_is_supported():
    added = change(before="")
    assert audit_changes([[added]], [added])["ok"]
    with pytest.raises(ValueError):
        audit_changes([[change(after="")]], [])


def test_cli_writes_failure_then_success_from_actual_jsonl(tmp_path):
    source, output = tmp_path / "names.jsonl", tmp_path / "report.json"
    source.write_text("\n".join(json.dumps(r) for r in [name(), name("b", "冰刃")]), encoding="utf-8")
    assert main(["names", "--definitions", str(source), "--out", str(output)]) == 1
    assert json.loads(output.read_text())["hard_blockers"] == 1
    source.write_text(json.dumps(name()), encoding="utf-8")
    assert main(["names", "--definitions", str(source), "--out", str(output)]) == 0
    with pytest.raises(SystemExit):
        main(["names", "--definitions", str(source), "--out", str(source)])
