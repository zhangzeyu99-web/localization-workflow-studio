"""Stable JSON boundary for glossary-first localization handoffs."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any

from glossary_extraction.constants import ACTION_TERMS, QUOTED_TERM_RE
from glossary_extraction.excel_io import file_digest, iter_raw_xlsx_sheets
from glossary_extraction.heuristics import (
    category_for,
    clean_text,
    extract_structured_term_pairs,
    is_valid_term,
)


VALID_DECISIONS = frozenset({"include", "reject", "needs_context"})
CATEGORY_MAP = {
    "rarity": "品质",
    "resource": "资源",
    "stat": "属性",
    "action": "动作",
    "activity": "活动",
    "mail": "邮件",
    "alliance": "联盟",
    "dungeon": "副本",
    "hero": "英雄",
    "monster": "怪物",
    "pet": "宠物",
    "equipment": "装备",
    "item": "道具",
    "skill": "技能",
    "emblem": "纹章",
    "ui": "UI",
    "needs_review": "待确认",
}
SOURCE_HEADERS = ("cn", "中文", "中文key", "简体中文", "source", "ori_string")
ID_HEADERS = ("id", "索引id", "唯一标识id")
CONTEXT_HEADERS = ("备注", "来源文件", "表名", "字段名", "字段名注释", "类型", "术语类型", "分类")
LOW_VALUE_RE = re.compile(
    r"^(?:已|未|可|暂无|当前|本次|今日|昨日|明日).{0,8}(?:领取|解锁|结束|开始|完成|开放|生效|拥有|获得|购买|使用)?$|"
    r"^(?:排行|进度|任务|活动|个人|公会|登录|累计)?奖励$|"
    r"^(?:获得|领取|查看|参与|使用|点击|前往)(?:奖励|活动|道具|详情|页面)$"
)
PLACEHOLDER_OR_CONFIG_RE = re.compile(r"(?:<@\d+>|\$?\{\d+\}|%[sd]|\\n|<[^>]+>|\[[^\]]+\]|\d)")
COMPOSITE_VARIANT_RE = re.compile(r"^.{2,}(?:神器胚|神器碎片|技能伤害|伤害提升|属性提升)$")
BRACKETED_TERM_RE = re.compile(r"【([^【】]{2,400})】")


def normalized_headers(row: list[object]) -> list[str]:
    return [clean_text(value).casefold() for value in row]


def find_header(rows: list[list[str]]) -> tuple[int, list[str], int, int | None] | None:
    for index, row in enumerate(rows[:50]):
        headers = normalized_headers(row)
        source_index = next((headers.index(name) for name in SOURCE_HEADERS if name in headers), None)
        if source_index is None:
            continue
        id_index = next((headers.index(name) for name in ID_HEADERS if name in headers), None)
        return index, headers, source_index, id_index
    return None


def infer_unnamed_language(path: Path, target_languages: list[str]) -> str:
    stem = path.stem.casefold()
    for language in target_languages:
        token = language.casefold()
        if re.search(rf"(?:^|[_\-]){re.escape(token)}(?:[_\-]|$)", stem):
            return language
        if token == "en" and "en_en" in stem:
            return language
    return ""


def translation_indexes(
    path: Path,
    headers: list[str],
    source_index: int,
    target_languages: list[str],
) -> dict[str, int]:
    indexes: dict[str, int] = {}
    for language in target_languages:
        key = language.casefold()
        if key in headers:
            indexes[language] = headers.index(key)
    inferred = infer_unnamed_language(path, target_languages)
    if inferred and inferred not in indexes and source_index + 1 < len(headers) and not headers[source_index + 1]:
        indexes[inferred] = source_index + 1
    return indexes


def text_at(row: list[object], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return clean_text(row[index])


def load_existing_glossary(
    path: Path,
    target_languages: list[str],
) -> tuple[set[str], int, dict[str, dict[str, object]]]:
    existing: set[str] = set()
    entries: dict[str, dict[str, object]] = {}
    rows_seen = 0
    for sheet_name, rows in iter_raw_xlsx_sheets(path):
        header = find_header(rows)
        if header is None:
            continue
        header_index, headers, source_index, _id_index = header
        lang_indexes = translation_indexes(path, headers, source_index, target_languages)
        for row_number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
            cn = text_at(row, source_index)
            if cn:
                rows_seen += 1
                key = cn.casefold()
                existing.add(key)
                entries.setdefault(
                    key,
                    {
                        "cn": cn,
                        "sheet": sheet_name,
                        "row": row_number,
                        "translations": {
                            language: text_at(row, lang_indexes.get(language))
                            for language in target_languages
                        },
                    },
                )
    return existing, rows_seen, entries


def candidate_terms(raw_source: str) -> list[str]:
    source = clean_text(raw_source)
    terms: list[str] = []
    if is_valid_term(source):
        terms.append(source)
    for structured_term, _translation in extract_structured_term_pairs(raw_source, ""):
        if is_valid_term(structured_term) and structured_term not in terms:
            terms.append(structured_term)
    for match in QUOTED_TERM_RE.finditer(raw_source):
        term = clean_text(match.group(1))
        if is_valid_term(term) and term not in terms:
            terms.append(term)
    for match in BRACKETED_TERM_RE.finditer(raw_source):
        term = clean_text(re.sub(r"<@\d+>", "", match.group(1)))
        if is_valid_term(term) and term not in terms:
            terms.append(term)
    return terms


def auto_decision(term: str, existing_cn: set[str]) -> tuple[str, str, str]:
    if term.casefold() in existing_cn:
        return "reject", CATEGORY_MAP.get(category_for(term), "待确认"), "existing_glossary"
    category = CATEGORY_MAP.get(category_for(term), "待确认")
    if LOW_VALUE_RE.match(term):
        return "reject", category if category != "待确认" else "UI", "low_value_prompt"
    if PLACEHOLDER_OR_CONFIG_RE.search(term):
        return "reject", category, "placeholder_or_config"
    if COMPOSITE_VARIANT_RE.match(term):
        return "reject", category if category != "待确认" else "道具", "composite_variant"
    if term in ACTION_TERMS or category != "待确认":
        return "needs_context", category, "category_is_not_term_approval"
    return "needs_context", "待确认", "manual_review_required"


def load_review(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"decisions": {}, "additional_candidates": []}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("review file must contain a JSON object")
    return raw


def export_candidates(
    input_paths: list[Path],
    existing_glossary: Path,
    target_languages: list[str],
    output_path: Path,
    review_file: Path | None = None,
) -> dict[str, object]:
    existing_cn, existing_rows, existing_entries = load_existing_glossary(
        existing_glossary,
        target_languages,
    )
    candidates: OrderedDict[str, dict[str, object]] = OrderedDict()
    source_evidence: list[dict[str, object]] = []
    input_summaries: list[dict[str, object]] = []
    all_sources: list[str] = []
    normalized_sources: list[str] = []

    for input_path in input_paths:
        file_rows = 0
        sheet_summaries = []
        for sheet_name, rows in iter_raw_xlsx_sheets(input_path):
            header = find_header(rows)
            if header is None:
                continue
            header_index, headers, source_index, id_index = header
            lang_indexes = translation_indexes(input_path, headers, source_index, target_languages)
            context_indexes = [i for i, header_name in enumerate(headers) if header_name in {x.casefold() for x in CONTEXT_HEADERS}]
            sheet_rows = 0
            for row_number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
                raw_source = "" if source_index >= len(row) else str(row[source_index] or "").strip()
                if not raw_source:
                    continue
                sheet_rows += 1
                file_rows += 1
                all_sources.append(raw_source)
                normalized_sources.append(clean_text(raw_source))
                evidence = {
                    "file": str(input_path),
                    "sheet": sheet_name,
                    "row": row_number,
                    "source": raw_source,
                }
                row_id = text_at(row, id_index)
                context = " | ".join(filter(None, (text_at(row, i) for i in context_indexes)))
                if row_id:
                    evidence["id"] = row_id
                if context:
                    evidence["context"] = context
                source_evidence.append(evidence)
                for term in candidate_terms(raw_source):
                    key = term.casefold()
                    candidate = candidates.setdefault(
                        key,
                        {
                            "cn": term,
                            "category": "待确认",
                            "evidence": [],
                            "translations": {language: "" for language in target_languages},
                            "decision": "needs_context",
                            "reason": "manual_review_required",
                        },
                    )
                    if len(candidate["evidence"]) < 8:
                        candidate["evidence"].append(evidence)
                    for language, column_index in lang_indexes.items():
                        value = text_at(row, column_index)
                        if value and not candidate["translations"][language]:
                            candidate["translations"][language] = value
            sheet_summaries.append({"sheet": sheet_name, "source_rows": sheet_rows})
        input_summaries.append({
            "file": str(input_path),
            "sha256": file_digest(input_path),
            "source_rows": file_rows,
            "sheets": sheet_summaries,
        })

    for candidate in candidates.values():
        decision, category, reason = auto_decision(str(candidate["cn"]), existing_cn)
        candidate["decision"] = decision
        candidate["category"] = category
        candidate["reason"] = reason

    review = load_review(review_file)
    decisions = review.get("decisions", {})
    if not isinstance(decisions, dict):
        raise ValueError("review decisions must be an object keyed by CN")
    for cn, raw_decision in decisions.items():
        key = clean_text(cn).casefold()
        if key not in candidates or not isinstance(raw_decision, dict):
            continue
        decision = clean_text(raw_decision.get("decision"))
        if decision not in VALID_DECISIONS:
            raise ValueError(f"invalid decision for {cn}: {decision}")
        candidates[key]["decision"] = decision
        if clean_text(raw_decision.get("category")):
            candidates[key]["category"] = clean_text(raw_decision.get("category"))
        candidates[key]["reason"] = clean_text(raw_decision.get("reason")) or "reviewed"

    additions = review.get("additional_candidates", [])
    if not isinstance(additions, list):
        raise ValueError("additional_candidates must be a list")
    for raw in additions:
        if not isinstance(raw, dict):
            continue
        cn = clean_text(raw.get("cn"))
        if not cn:
            continue
        decision = clean_text(raw.get("decision")) or "needs_context"
        if decision not in VALID_DECISIONS:
            raise ValueError(f"invalid decision for {cn}: {decision}")
        evidence_contains = clean_text(raw.get("evidence_contains")) or cn
        matched = [item for item in source_evidence if evidence_contains in clean_text(item.get("source"))][:8]
        translations = {language: "" for language in target_languages}
        supplied_translations = raw.get("translations", {})
        if isinstance(supplied_translations, dict):
            for language in target_languages:
                translations[language] = clean_text(supplied_translations.get(language))
        candidates[cn.casefold()] = {
            "cn": cn,
            "category": clean_text(raw.get("category")) or "待确认",
            "evidence": matched,
            "translations": translations,
            "decision": decision,
            "reason": clean_text(raw.get("reason")) or "reviewed_sentence_evidence",
        }

    # 审阅和句内补充都不能绕过母表去重，更不能覆盖已有译文。
    for key, candidate in candidates.items():
        if key in existing_entries:
            candidate['decision'] = 'reject'
            candidate['reason'] = 'existing_glossary'
            candidate['translations'] = dict(existing_entries[key]['translations'])

    rows = list(candidates.values())
    existing_incomplete = []
    for entry in existing_entries.values():
        translations = dict(entry["translations"])
        missing_languages = [language for language in target_languages if not translations.get(language)]
        cn = str(entry["cn"])
        matched_evidence = [
            evidence
            for evidence in source_evidence
            if len(cn) >= 2 and cn in clean_text(evidence.get("source"))
        ][:8]
        if missing_languages and matched_evidence:
            existing_incomplete.append(
                {
                    "cn": cn,
                    "missing_languages": missing_languages,
                    "translations": translations,
                    "evidence": matched_evidence,
                }
            )
    decision_counts = Counter(str(row["decision"]) for row in rows)
    payload: dict[str, object] = {
        "schema_version": 1,
        "task": "glossary_candidate_export",
        "target_languages": target_languages,
        "inputs": input_summaries,
        "existing_glossary": {
            "file": str(existing_glossary),
            "sha256": file_digest(existing_glossary),
            "rows": existing_rows,
            "unique_cn": len(existing_cn),
        },
        "summary": {
            "source_rows": len(all_sources),
            "unique_source_texts": len(set(all_sources)),
            "normalized_unique_source_texts": len(set(normalized_sources)),
            "candidate_count": len(rows),
            "decisions": {key: decision_counts.get(key, 0) for key in ("include", "reject", "needs_context")},
            "existing_incomplete": len(existing_incomplete),
            "existing_incomplete_by_language": {
                language: sum(1 for row in existing_incomplete if language in row["missing_languages"])
                for language in target_languages
            },
            "include_missing_translations": {
                language: sum(1 for row in rows if row["decision"] == "include" and not row["translations"].get(language))
                for language in target_languages
            },
        },
        "existing_incomplete": existing_incomplete,
        "candidates": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export reviewed glossary candidates as stable JSON.")
    parser.add_argument("--input", action="append", required=True, type=Path, help="Source XLSX. Repeat for multiple inputs.")
    parser.add_argument("--existing-glossary", required=True, type=Path, help="Existing glossary XLSX used for CN deduplication.")
    parser.add_argument("--target-langs", required=True, help="Comma-separated target language codes.")
    parser.add_argument("--output", required=True, type=Path, help="Output candidates.json path.")
    parser.add_argument("--review-file", type=Path, help="Optional reviewed decisions and sentence-level additions JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    languages = [item.strip().upper() for item in args.target_langs.split(",") if item.strip()]
    if not languages:
        raise SystemExit("--target-langs must contain at least one language code")
    payload = export_candidates(
        input_paths=args.input,
        existing_glossary=args.existing_glossary,
        target_languages=languages,
        output_path=args.output,
        review_file=args.review_file,
    )
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
