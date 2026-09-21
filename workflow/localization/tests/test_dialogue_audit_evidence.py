import pytest

from utils.large_text_multilingual_proofread import _validate_audit, _review_signature


def test_dialogue_accept_requires_meaning_evidence_and_disagreement_blocks():
    fix = {"review_key": "a", "lang": "FR", "semantic_check_required": True}
    decision = {"review_key": "a", "lang": "FR", "decision": "ACCEPT", "final": "Texte."}
    with pytest.raises(ValueError, match="semantic"):
        _validate_audit([fix], [decision])
    check = {"source_meaning": "Do not worry about the issue.", "final_meaning": "Do not worry about the head.",
             "meaning_preserved": False, "roles_preserved": True, "tone_preserved": True}
    with pytest.raises(ValueError, match="semantic"):
        _validate_audit([fix], [{**decision, "semantic_check": check}])
    check.update(final_meaning="Do not worry about the issue.", meaning_preserved=True)
    assert _validate_audit([fix], [{**decision, "semantic_check": check}])[("a", "FR")]["semantic_check"] == check
    assert _validate_audit([fix], [{**decision, "decision": "REVERT"}])[("a", "FR")]["decision"] == "REVERT"


def test_dialogue_evidence_enters_signature():
    base = {"cn": "他做好了。", "translations": {"DE": "Er hat es gemacht."}}
    assert _review_signature({**base, "dialogue_evidence": {"turns": ["der Tisch"]}}, ["DE"]) != _review_signature(
        {**base, "dialogue_evidence": {"turns": ["die Suppe"]}}, ["DE"])
    from utils.large_text_multilingual_proofread import _language_evidence
    evidence={'turns':[{'cn':'桌子','translations':{'DE':'Tisch','FR':'table'}}]}
    assert _language_evidence(evidence,'DE')['turns'][0]['translations']=={'DE':'Tisch'}
    assert 'FR' in evidence['turns'][0]['translations']


def test_scene_evidence_keeps_target_antecedents_and_stays_in_scene():
    from utils.large_text_multilingual_proofread import _attach_dialogue_evidence
    import json

    rows = [{"key": str(i), "source_file": "a", "sheet": "S", "row": i + 2, "cn": "台词",
             "translation_source": "A line.", "context": json.dumps({"type": "dialogue", "scene": scene}),
             "translations": {"DE": target}} for i, (scene, target) in enumerate([
                 ("one", "Der Tisch"), ("one", "Er glänzt."), ("two", "Other scene")])]
    enriched = _attach_dialogue_evidence(rows)
    assert enriched[1]["dialogue_evidence"]["turns"][0]["translations"]["DE"] == "Der Tisch"
    assert len(enriched[1]["dialogue_evidence"]["turns"]) == 2
    assert "dialogue_evidence" not in rows[1]


def test_blind_target_reading_does_not_receive_source_or_reviewer_reason():
    from utils.large_text_multilingual_executor import OpenAICompatibleClient

    calls = []
    class Client(OpenAICompatibleClient):
        def __init__(self):
            pass

        def _chat_json(self, prompt, payload):
            calls.append(payload)
            if len(calls) == 1:
                assert set(payload["rows"][0]) == {"review_key", "lang", "text"}
                return {"rows": [{"review_key": "a", "lang": "FR", "meaning": "Worry about a head.",
                                  "predicate_object": "head", "tone": "odd reassurance"}]}
            assert payload["suggestions"][0]["independent_target_reading"]["predicate_object"] == "head"
            return {"rows": [{"review_key": "a", "lang": "FR", "decision": "ACCEPT", "final": "Ne te fais pas de souci pour ta jolie petite tête."}]}

    result = Client().audit_batch([{"review_key": "a", "lang": "FR", "suggested": "Ne te soucie pas de ta tête.",
                                   "cn": "不要为这事操心", "source_mode":"en", "translation_source":"Don't worry your pretty little head about it.",
                                   "current": "Original.", "reason": "untrusted", "semantic_check_required": True}])
    assert result[0]["independent_target_reading"]["meaning"] == "Worry about a head."
    assert result[0]['decision'] == 'REVERT' and result[0]['final'] == 'Original.'
    assert len(calls) == 2


def test_term_waiver_bound_to_exact_target_source_and_context():
    from utils.large_text_multilingual_gate import _check_required_terms
    row = {"cn": "艾达和你", "translation_source": "You and Ada", "context": "Ada was named above.",
           "term_hits": [{"source": "艾达", "required": True, "translations": {"DE": "Ada"}}]}
    waiver = {"source": "艾达", "lang": "DE", "target": "Ihr beide", "cn": row["cn"],
              "translation_source": row["translation_source"], "context": row["context"], "reason": "Natural reference to explicit antecedents."}
    for changes, target, blocked in [({}, "Ihr beide", False), ({}, "Jemand", True),
                                     ({"cn": "另一个源文"}, "Ihr beide", True),
                                     ({"context": "Different scene"}, "Ihr beide", True)]:
        issues = []
        _check_required_terms(issues, {**row, "term_waivers": [waiver], **changes}, "row", "DE", target)
        assert bool(issues) == blocked


def test_scene_target_evidence_reaches_real_review_audit_and_survives_revert(tmp_path):
    import json
    from utils.large_text_multilingual_proofread import run_deep_proofread
    from utils.large_text_multilingual_runner import build_manifest

    class Reviewer:
        def review_batch(self, rows, target_langs):
            result = []
            for row in rows:
                assert row['dialogue_evidence']['turns'][0]['translations']['DE'] == 'Der Tisch.'
                result.append({'review_key':row['review_key'], 'lang':'DE',
                               'status':'FIX' if row['cn']=='它很亮。' else 'KEEP',
                               'suggested':'Sie glänzt.' if row['cn']=='它很亮。' else row['translations']['DE'],
                               'reason':'wrong antecedent assumption', 'dialogue_evidence':{'speaker':'untrusted'}})
            return result

    class Auditor:
        def audit_batch(self, rows):
            assert len(rows)==2
            for row in rows:
                assert row['semantic_check_required'] is True
                assert row['dialogue_evidence']['speaker']=='unknown'
                assert row['dialogue_evidence']['turns'][0]['translations']['DE']=='Der Tisch.'
            return [{'review_key':row['review_key'],'lang':'DE',
                     'decision':'ACCEPT' if row['status']=='KEEP' else 'REVERT',
                     'final':row['current'], 'reason':'Tisch is masculine.',
                     'semantic_check':{'source_meaning':'The table.','final_meaning':'The table.',
                                       'meaning_preserved':True,'roles_preserved':True,'tone_preserved':True}}
                    for row in rows]

    rows=[{'key':str(i),'source_file':'a.xlsx','sheet':'S','row':i+2,'cn':cn,
           'context':json.dumps({'type':'dialogue','scene':'one'}), 'translations':{'DE':de}}
          for i,(cn,de) in enumerate([('桌子。','Der Tisch.'),('它很亮。','Er glänzt.')])]
    path=tmp_path/'cache.jsonl'
    path.write_text('\n'.join(json.dumps(row,ensure_ascii=False) for row in rows)+'\n',encoding='utf8')
    manifest=build_manifest(work_dir=tmp_path/'runner',items_jsonl=path,source_rows_jsonl=None,
                            target_langs=['DE'],workbook_count=1,relay_config=None,proofread_mode='full')
    result=run_deep_proofread(__import__('pathlib').Path(manifest['manifest_path']),initial_cache=path,reviewer=Reviewer(),auditor=Auditor())
    assert result.changed_cells==0 and result.reverted_changes==1


def test_semantic_fixture_reaches_cache_and_audit_gates(tmp_path):
    import json
    from pathlib import Path
    from utils.large_text_multilingual_gate import cache_lint
    from utils.semantic_regression import known_semantic_regressions

    cases=json.loads((Path(__file__).parents[1]/'fixtures/quality_regression.json').read_text(encoding='utf8'))['semantic_regression_cases']
    for index,case in enumerate(cases):
        assert bool(known_semantic_regressions(case,case['lang'],case['target']))==case['blocked']
        row={**case,'key':str(index),'cn':case['translation_source'],'translations':{case['lang']:case['target']}}
        path=tmp_path/'cache.jsonl'
        path.write_text(json.dumps(row,ensure_ascii=False)+'\n',encoding='utf8')
        issues=cache_lint(path,target_langs=[case['lang']])['issues']
        assert any(x['type']=='known_semantic_regression' for x in issues)==case['blocked']
        fix={**case,'review_key':str(index)}
        decision={'review_key':str(index),'lang':case['lang'],'decision':'ACCEPT','final':case['target']}
        if case['blocked']:
            with pytest.raises(ValueError,match='known semantic regression'):
                _validate_audit([fix],[decision])
        else:
            _validate_audit([fix],[decision])
