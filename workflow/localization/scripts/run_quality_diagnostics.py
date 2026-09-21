"""只读统计评估覆盖和重复资源 ID，输出独立诊断 JSON。"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.quality_diagnostics import diagnose_scope


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache-jsonl', type=Path, required=True)
    p.add_argument('--coverage', type=Path, required=True, help='JSON: reviewed/unresolved pairs and sampling')
    p.add_argument('--target-langs', required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if a.out.exists() or a.out.resolve() in {a.cache_jsonl.resolve(), a.coverage.resolve()}:
        p.error('output must be a new file')
    rows = [json.loads(s) for s in a.cache_jsonl.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
    coverage = json.loads(a.coverage.read_text(encoding='utf-8-sig'))
    report = diagnose_scope(rows, a.target_langs.split(','), coverage['reviewed'],
                            unresolved=coverage.get('unresolved', []), sampling=coverage['sampling'])
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ['population_rows', 'unique_reviewed_cells', 'unresolved_cells', 'overall_quality_score']}))
    return 2 if report['conflicting_id_groups'] or report['duplicate_id_groups'] or report['unresolved_cells'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
