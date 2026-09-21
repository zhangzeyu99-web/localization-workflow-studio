"""Product-side large-text helpers.

This module intentionally keeps behavioral parity with the local harness
source of truth at ``workflow/localization/utils/large_text_multilingual_gate.py``.
That file remains the canonical implementation for preflight sizing, cache
lint parsing rules (numbers, word multipliers, CJK filtering, machine-like
bracket tokens) and readback checks used by local agent workflows. This
module ports the same pure logic so the product backend does not depend on
cross-tree imports or local-agent file-system assumptions; parity is
verified by ``backend/tests/test_large_text_productization.py`` which
compares representative rows against the workflow gate module directly.

Do not let this module drift from the workflow gate without updating the
parity tests. If the two disagree, the workflow gate wins.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from ..languages import SOURCE_HEADER_ALIASES, target_aliases
from .large_text_rules.core import (  # noqa: F401 - public helper compatibility
    SOURCE_HEADERS, TOKEN_RE, _check_required_terms, pair_integrity_issues,
    is_auto_protected_token, protected_tokens, parse_number_token,
    numeric_values, source_numeric_values, numeric_value_present, add_issue,
)
from .large_text_rules.language_config import target_header_candidates
from .large_text_rules.review_findings import unresolved_review_detail

WORKFLOW_VERSION = "large_text_product_v1"
ALLOWED_MODES = {"auto", "strict", "off"}

# Sheets emitted by the local QA harness (workflow/localization/process_language.py)
# alongside the primary translation sheet. They carry review/reference columns
# only (no full target-language coverage) and must not be treated as delivery
# content when checking for missing target columns or blank target cells.
REVIEW_ONLY_SHEET_TITLES = {"需确认", "术语行筛选"}


def normalize_large_text_mode(value: str | None) -> str:
    mode = str(value or "auto").strip().lower()
    if mode not in ALLOWED_MODES:
        return "auto"
    return mode


def row_key(row: dict[str, Any], fallback: int) -> str:
    return str(row.get("key") or row.get("id") or row.get("para_id") or fallback)


def source_text(row: dict[str, Any]) -> str:
    return str(row.get("cn") or row.get("CN") or row.get("source") or "")


def row_translation(row: dict[str, Any], lang: str) -> str:
    translations = row.get("translations")
    if isinstance(translations, dict):
        value = translations.get(lang) or translations.get(lang.upper())
        return "" if value is None else str(value)
    value = row.get(lang) or row.get(lang.upper())
    return "" if value is None else str(value)


def explicit_translation_langs(row: dict[str, Any]) -> set[str]:
    translations = row.get("translations")
    if isinstance(translations, dict):
        return {str(key).lower() for key in translations}
    return set()


def build_large_text_preflight(
    rows: list[dict[str, Any]],
    *,
    target_languages: list[str],
    source_rows: int | None = None,
    workbook_count: int = 1,
    full_proofread: bool = False,
) -> dict[str, Any]:
    target_langs = [str(lang).strip().lower() for lang in target_languages if str(lang).strip()]
    unique_keys = {row_key(row, index) for index, row in enumerate(rows, 1)}
    long_text_items = [row for row in rows if int(row.get("char_len") or len(source_text(row))) > 300]
    estimated_cells = len(unique_keys) * len(target_langs)
    reasons: list[str] = []
    if len(unique_keys) > 5000:
        reasons.append("unique_items>5000")
    if len(target_langs) > 4:
        reasons.append("target_languages>4")
    if workbook_count > 1:
        reasons.append("workbook_count>1")
    if long_text_items:
        reasons.append("long_text_items>0")
    if full_proofread:
        reasons.append("full_proofread_requested")
    recommended_shards = 1
    if reasons:
        recommended_shards = max(2, min(8, (estimated_cells // 25000) + 2))
    return {
        "workflow": WORKFLOW_VERSION,
        "unique_items": len(unique_keys),
        "source_rows": source_rows,
        "target_languages": target_langs,
        "target_language_count": len(target_langs),
        "estimated_target_cells": estimated_cells,
        "long_text_items": len(long_text_items),
        "workbook_count": workbook_count,
        "large_pack": bool(reasons),
        "large_pack_reasons": reasons,
        "recommended_translation_shards": recommended_shards,
        "recommended_deep_proofread_shards": max(recommended_shards, 4) if full_proofread else recommended_shards,
    }


def build_translation_cache_rows(
    workpack_rows: list[dict[str, Any]],
    translated_rows: list[dict[str, Any]],
    language: str,
) -> list[dict[str, Any]]:
    by_id = {str(row.get("id")): str(row.get("translation") or "") for row in translated_rows}
    lang = language.lower()
    cache_rows: list[dict[str, Any]] = []
    for index, row in enumerate(workpack_rows, 1):
        key = row_key(row, index)
        item = dict(row)
        item["key"] = key
        item["source"] = source_text(row)
        item["translations"] = {lang: by_id.get(str(row.get("id")), "")}
        cache_rows.append(item)
    return cache_rows


def cache_lint_rows(cache_rows: list[dict[str, Any]], *, target_languages: list[str]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    unauthorized: Counter[str] = Counter()
    langs = [lang.lower() for lang in target_languages]
    requested = set(langs)
    if not cache_rows:
        add_issue(issues, "empty_cache", "", "", "cache contains no source rows")
    if not langs:
        add_issue(issues, "target_languages_missing", "", "", "no target languages requested")
    for index, row in enumerate(cache_rows, 1):
        key = row_key(row, index)
        if key in seen:
            add_issue(issues, "duplicate_key", key, "", "cache contains duplicate source key")
        seen.add(key)
        extras = explicit_translation_langs(row) - requested
        for lang in sorted(extras):
            unauthorized[lang] += 1
            add_issue(issues, "unauthorized_language", key, lang, "translation cache contains a language that was not requested")

        unresolved = unresolved_review_detail(row)
        if unresolved:
            add_issue(issues, "unresolved_review_finding", key, "", unresolved)
        for lang in langs:
            target = row_translation(row, lang).strip()
            if row.get("opaque_payload_preserved") is True:
                if target != source_text(row).strip():
                    add_issue(issues, "opaque_payload_changed", key, lang, "opaque source payload must be preserved exactly")
                continue
            if not target:
                add_issue(issues, "empty_translation", key, lang, "target translation is empty")
                continue
            for issue_type, detail in pair_integrity_issues(row, lang, target):
                add_issue(issues, issue_type, key, lang, detail)
            _check_required_terms(issues, row, key, lang, target)
    by_type = Counter(issue["type"] for issue in issues)
    return {
        "workflow": WORKFLOW_VERSION,
        "checked_items": len(cache_rows),
        "target_languages": langs,
        "hard_blockers": len(issues),
        "hard_by_type": dict(sorted(by_type.items())),
        "unauthorized_languages": dict(sorted(unauthorized.items())),
        "issues": issues,
        "ok_to_apply": len(issues) == 0,
    }


def _looks_like_translation_sheet(headers: list[str], target_langs: list[str]) -> bool:
    header_set = {header for header in headers if header}
    aliases = {name for lang in target_langs for name in _delivery_target_headers(lang)}
    if header_set.intersection(aliases):
        return True
    return bool(header_set.intersection(SOURCE_HEADERS | {name.upper() for name in SOURCE_HEADER_ALIASES}))


def _delivery_target_headers(lang: str) -> set[str]:
    # Studio uses VN internally; retain product aliases alongside upstream VI.
    return {name.upper() for name in set(target_aliases(lang)) | target_header_candidates(lang)}


def readback_gate_files(paths: list[Path], *, target_languages: list[str]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    targets = [lang.upper() for lang in target_languages]
    checked_cells = 0
    checked_workbooks = 0
    for path in paths:
        path = Path(path)
        files.append({"name": path.name, "bytes": path.stat().st_size if path.exists() else 0})
        if not path.exists():
            add_issue(issues, "delivery_file_missing", path.name, "", "delivery file does not exist")
            continue
        if path.suffix.lower() not in {".xlsx", ".xlsm"}:
            continue
        workbook = load_workbook(path, read_only=True, data_only=True)
        recognized = False
        try:
            for sheet in workbook.worksheets:
                if sheet.title in REVIEW_ONLY_SHEET_TITLES:
                    continue
                first_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
                headers = [str(value).strip().upper() if value is not None else "" for value in first_row]
                if not _looks_like_translation_sheet(headers, targets):
                    continue
                recognized = True
                source_headers = SOURCE_HEADERS | {name.upper() for name in SOURCE_HEADER_ALIASES}
                source_col = next((index for index, header in enumerate(headers) if header in source_headers), None)
                if source_col is None:
                    add_issue(issues, "source_column_missing", f"{path.name}:{sheet.title}", "", "cannot validate targets without a source column")
                    continue
                id_col = next((index for index, header in enumerate(headers) if header in {"ID", "KEY", "索引ID"}), None)
                target_columns: list[tuple[str, int]] = []
                for lang in targets:
                    candidates = _delivery_target_headers(lang)
                    matches = [index for index, header in enumerate(headers) if header in candidates and index != id_col]
                    if len(matches) > 1:
                        add_issue(issues, "ambiguous_target_column", f"{path.name}:{sheet.title}", lang, "multiple columns match target language")
                        continue
                    col_index = matches[0] if matches else None
                    if col_index is None:
                        add_issue(issues, "target_column_missing", f"{path.name}:{sheet.title}", lang, "target language column is missing")
                        continue
                    target_columns.append((lang, col_index))
                if not target_columns:
                    continue
                for row_index, row_values in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
                    source = row_values[source_col] if source_col < len(row_values) else None
                    row_id = row_values[id_col] if id_col is not None and id_col < len(row_values) else None
                    if (source is None or str(source).strip() == "") and (row_id is None or str(row_id).strip() == ""):
                        continue
                    for lang, col_index in target_columns:
                        checked_cells += 1
                        value = row_values[col_index] if col_index < len(row_values) else None
                        if value is None or str(value).strip() == "":
                            add_issue(issues, "blank_target_cell", f"{path.name}:{sheet.title}!R{row_index}C{col_index + 1}", lang, "target cell is blank")
                        else:
                            for issue_type, detail in pair_integrity_issues({"cn": str(source or "")}, lang, str(value)):
                                add_issue(issues, issue_type, f"{path.name}:{sheet.title}!R{row_index}C{col_index + 1}", lang, detail)
            if recognized:
                checked_workbooks += 1
            else:
                add_issue(issues, "translation_sheet_missing", path.name, "", "no recognized source/target sheet")
        finally:
            workbook.close()
    if not checked_workbooks or not checked_cells:
        add_issue(issues, "empty_delivery", "", "", "no translated cells were checked")
    by_type = Counter(issue["type"] for issue in issues)
    return {
        "workflow": WORKFLOW_VERSION,
        "files": files,
        "checked_workbooks": checked_workbooks,
        "checked_target_cells": checked_cells,
        "target_languages": target_languages,
        "hard_blockers": len(issues),
        "hard_by_type": dict(sorted(by_type.items())),
        "issues": issues,
        "readback_verified": len(issues) == 0,
    }


LONG_TASK_REVIEW_SECONDS = 3600


def _gate_line(label: str, gate: dict[str, Any]) -> str:
    status = str(gate.get("status") or ("passed" if int(gate.get("hard_blockers") or 0) == 0 else "failed"))
    reason = f", reason={gate.get('reason')}" if status in {"skipped", "waived"} and gate.get("reason") else ""
    return f"- {label}: status={status}{reason}, hard={gate.get('hard_blockers', 'n/a')}"


def render_large_text_retro(metrics: dict[str, Any]) -> str:
    progress = metrics.get("translation_progress") or {}
    elapsed = int(progress.get("elapsed_seconds") or 0)
    long_status = "triggered" if elapsed >= LONG_TASK_REVIEW_SECONDS else "not_triggered"
    return f"""# 大文本处理复盘

## 执行规模

- unique_items: {(metrics.get("preflight") or {}).get("unique_items", "n/a")}
- estimated_target_cells: {(metrics.get("preflight") or {}).get("estimated_target_cells", "n/a")}
- total_rows: {progress.get("total_rows", "n/a")}
- completed_rows: {progress.get("completed_rows", "n/a")}

## 执行门禁结果

{_gate_line("cache-lint", metrics.get("cache_lint") or {})}
{_gate_line("readback-gate", metrics.get("readback_gate") or {})}

## 长任务复盘触发

- status={long_status}, threshold=3600s, elapsed={elapsed}s
- review_focus=判断耗时是否只是任务规模导致；检查失败/重试/跳过门禁/意外修复；重复出现或可机器检查的问题沉淀为测试、gate 或文档，偶发问题只记录。
"""


__all__ = [name for name in globals() if not name.startswith("_")]
