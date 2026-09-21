"""评估范围与资源身份检查；覆盖率不推导语言质量或发布通过。"""
from collections import defaultdict
import json


def diagnose_scope(rows, languages, reviewed, *, unresolved=(), sampling='purposive'):
    if sampling not in {'purposive', 'stratified', 'census'}:
        raise ValueError('unknown sampling method')
    if not rows or not languages or len(set(languages)) != len(languages):
        raise ValueError('nonempty rows and unique languages required')
    keys = [str(r['key']) for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError('duplicate physical row key')
    population = {(k, lang) for k in keys for lang in languages}
    seen = {tuple(cell) for cell in reviewed}
    unknown = {tuple(cell) for cell in unresolved}
    if not seen <= population or not unknown <= population:
        raise ValueError('coverage or unresolved cell outside source population')
    groups = defaultdict(list)
    for r in rows:
        if not str(r.get('id', '')).strip():
            raise ValueError('resource id required')
        groups[(r.get('file', ''), r.get('sheet', ''), str(r['id']))].append(r)
    conflicts, duplicates = [], []
    for (file, sheet, ident), members in groups.items():
        if len(members) < 2:
            continue
        signatures = {json.dumps({'source': r.get('translation_source'), 'cn': r.get('cn'),
                                  'translations': r.get('translations')}, sort_keys=True, ensure_ascii=False)
                      for r in members}
        item = {'file': file, 'sheet': sheet, 'id': ident, 'keys': [r['key'] for r in members]}
        (conflicts if len(signatures) > 1 else duplicates).append(item)
    return {'population_rows': len(rows), 'population_cells': len(population),
            'unique_reviewed_cells': len(seen), 'resolved_reviewed_cells': len(seen-unknown),
            'unresolved_cells': len(unknown), 'sampling': sampling,
            'full_semantic_review': sampling == 'census' and seen == population,
            'overall_quality_score': None,
            'score_limit': 'Coverage is not quality; purposive defect indices cannot estimate overall quality.',
            'conflicting_id_groups': conflicts, 'duplicate_id_groups': duplicates,
            'release_ready': False,
            'release_limit': 'This diagnostic is not an acceptance gate; semantic and runtime acceptance remain separate.'}
