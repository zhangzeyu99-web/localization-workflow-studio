"""Read-only gates for explicit name definitions and cumulative repair deliveries."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import unicodedata


def normalized_name(text: str) -> str:
    """Ignore presentation differences, preserving accents, letters and numbers."""
    return re.sub(r"[\W_]", "", unicodedata.normalize("NFKC", text).casefold())


def _key(row: dict) -> tuple[str, str, str]:
    if not isinstance(row, dict):
        raise ValueError("each record must be an object")
    for field in ("scope", "id", "lang", "cn"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ValueError(f"nonempty string required: {field}")
    return row["scope"], row["id"], row["lang"].upper()


def _text(row: dict, field: str, *, allow_blank: bool = False) -> str:
    if not isinstance(row.get(field), str) or (not allow_blank and not row[field].strip()):
        raise ValueError(f"nonempty string required: {field}")
    return row[field]


def scan_names(rows: list[dict], *, approvals: list[dict] | None = None,
               require_distinct: bool = False, glossary: list[dict] | None = None) -> dict:
    """Definitions only: never infer names from arbitrary description substrings."""
    if not rows:
        raise ValueError("empty definition input")
    groups = defaultdict(list)
    seen = {}
    issues = []
    for row in rows:
        key = _key(row)
        text = _text(row, "text")
        normalized = normalized_name(text)
        if not normalized:
            raise ValueError("name contains no letters or numbers")
        if key in seen:
            if (row["cn"], text) != seen[key]:
                issues.append({"type": "definition_id_conflict", "key": key})
            continue
        seen[key] = (row["cn"], text)
        groups[key[0], key[2], normalized].append(row)
    collisions = []
    valid_approvals = {a.get("fingerprint") for a in approvals or []
                       if a.get("decision") == "allow_shared"
                       and isinstance(a.get("reason"), str) and a["reason"].strip()}
    for (scope, lang, target), members in sorted(groups.items()):
        if len({r["cn"].strip() for r in members}) < 2:
            continue
        signature = sorted((r["id"], r["cn"], r["text"]) for r in members)
        fingerprint = hashlib.sha256(json.dumps([scope, lang, signature], ensure_ascii=False).encode()).hexdigest()
        approved = not require_distinct and fingerprint in valid_approvals
        collision = {"scope": scope, "lang": lang, "normalized_target": target,
                     "fingerprint": fingerprint, "members": members, "approved": approved}
        collisions.append(collision)
        if not approved:
            issues.append({"type": "unresolved_name_collision", "fingerprint": fingerprint})
    if glossary is not None:
        terms = {}
        for row in glossary:
            key = _key(row)
            term_key = key[0], row["cn"], key[2]
            text = _text(row, "text")
            if term_key in terms and terms[term_key] != text:
                issues.append({"type": "glossary_definition_conflict", "key": term_key})
            terms[term_key] = text
        for (scope, resource_id, lang), (cn, text) in seen.items():
            expected = terms.get((scope, cn, lang))
            if expected is None or expected != text:
                issues.append({"type": "glossary_missing" if expected is None else "glossary_mismatch",
                               "key": (scope, resource_id, lang), "cn": cn,
                               "text": text, "expected": expected})
    return {"checked_definitions": len(seen), "collision_groups": len(collisions),
            "collisions": collisions, "issues": issues, "hard_blockers": len(issues),
            "ok": not issues}


def audit_changes(rounds: list[list[dict]], final: list[dict]) -> dict:
    """Verify earliest-before/latest-after coverage from chronological change ledgers."""
    if not rounds or not any(rounds):
        raise ValueError("empty change history")
    chain = {}
    issues = []
    for rows in rounds:
        duplicates = set()
        for row in rows:
            key = _key(row)
            before, after = _text(row, "before", allow_blank=True), _text(row, "after")
            event = key, row["cn"], before, after
            if event in duplicates:  # Same logical change in two physical export formats.
                continue
            duplicates.add(event)
            if key in chain:
                previous = chain[key]
                if previous["cn"] != row["cn"]:
                    issues.append({"type": "source_changed_for_id", "key": key})
                if before != previous["after"]:
                    issues.append({"type": "broken_change_chain", "key": key})
                chain[key] = {**row, "before": previous["before"]}
            else:
                chain[key] = dict(row)
    expected = {k: r for k, r in chain.items() if r["before"] != r["after"]}
    delivered = {}
    for row in final:
        key = _key(row)
        _text(row, "before", allow_blank=True)
        _text(row, "after")
        if key in delivered:
            issues.append({"type": "duplicate_delivery_cell", "key": key})
        delivered[key] = row
    for key, row in expected.items():
        actual = delivered.get(key)
        if actual is None:
            issues.append({"type": "missing_delivery_cell", "key": key})
        elif any(row[f] != actual[f] for f in ("cn", "before", "after")):
            issues.append({"type": "stale_or_misaligned_delivery", "key": key})
    for key in delivered.keys() - expected.keys():
        issues.append({"type": "extra_delivery_cell", "key": key})
    return {"expected_cells": len(expected), "delivered_cells": len(delivered),
            "issues": issues, "hard_blockers": len(issues), "ok": not issues}


def _read(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("each JSONL record must be an object")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    names = sub.add_parser("names")
    names.add_argument("--definitions", type=Path, required=True)
    names.add_argument("--glossary", type=Path)
    names.add_argument("--approvals", type=Path)
    names.add_argument("--require-distinct", action="store_true")
    changes = sub.add_parser("changes")
    changes.add_argument("--round", type=Path, action="append", required=True, dest="rounds")
    changes.add_argument("--final", type=Path, required=True)
    for command in (names, changes):
        command.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    inputs = ([args.definitions, args.glossary, args.approvals] if args.command == "names"
              else [*args.rounds, args.final])
    if any(p and p.resolve() == args.out.resolve() for p in inputs):
        parser.error("output must not overwrite an input")
    try:
        if args.command == "names":
            report = scan_names(_read(args.definitions),
                                glossary=_read(args.glossary) if args.glossary else None,
                                approvals=_read(args.approvals) if args.approvals else None,
                                require_distinct=args.require_distinct)
        else:
            report = audit_changes([_read(p) for p in args.rounds], _read(args.final))
    except (ValueError, TypeError, KeyError, OSError) as exc:
        report = {"ok": False, "hard_blockers": 1, "issues": [{"type": "invalid_input", "detail": str(exc)}]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"issues", "collisions"}}, ensure_ascii=False))
    return 0 if report["ok"] else 1
