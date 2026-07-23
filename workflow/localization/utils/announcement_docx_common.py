"""Shared constants and helpers for the announcement DOCX harness.

Implementation module split out of utils/announcement_docx_harness.py. Import
these symbols through utils.announcement_docx_harness to keep the public
surface stable.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

TARGET_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("EN", "en"),
    ("KR", "ko"),
    ("JP", "ja"),
    ("FR", "fr"),
    ("DE", "de"),
    ("RU", "ru"),
    ("IT", "it"),
    ("ES", "es"),
    ("PT", "pt"),
    ("TR", "tr"),
    ("VI", "vi"),
    ("IDN", "idn"),
    ("TH", "th"),
    ("AR", "ar"),
)
SUPPORTED_LANGUAGES: tuple[tuple[str, str], ...] = (
    *TARGET_LANGUAGES,
    ("KO", "ko"),
    ("JA", "ja"),
    ("TK", "tr"),
    ("ID", "idn"),
)
CANONICAL_LANGUAGE_HEADER = {code: header for header, code in TARGET_LANGUAGES}
LANGUAGE_CODE_BY_HEADER = {header: code for header, code in SUPPORTED_LANGUAGES}

FIXED_COLUMNS = (
    "source_file",
    "para_id",
    "para_index",
    "style",
    "CN",
    "protected_tokens",
    "term_hits_json",
)
SENTENCE_ADAPTATIONS_COLUMN = "sentence_adaptations_json"
PREPARED_COLUMNS = (*FIXED_COLUMNS, SENTENCE_ADAPTATIONS_COLUMN)
TRANSLATION_WORKBOOK_NAME = "announcement_translation_workbook.xlsx"
MANIFEST_NAME = "manifest.json"
QA_SUMMARY_NAME = "QA摘要.xlsx"
AI_RESPONSE_PREFIX = "ai_response_"
WORK_DIR_NAME = "_work"
HARNESS_DIR_NAME = "announcement_docx"

_CJK_RE = re.compile(r"[\u3400-\u9fff]")


def _resolve_language_pairs(
    languages: list[str] | None,
) -> list[tuple[str, str]]:
    if not languages:
        return list(TARGET_LANGUAGES)
    selected_headers = _resolve_language_headers(languages, valid_languages=SUPPORTED_LANGUAGES)
    language_by_header = {header: code for header, code in TARGET_LANGUAGES}
    return [(header, language_by_header[header]) for header in selected_headers]


def _resolve_language_headers(
    languages: list[str] | None,
    *,
    valid_languages: list[tuple[str, str]] | tuple[tuple[str, str], ...] = TARGET_LANGUAGES,
) -> list[str]:
    valid_headers = {header for header, _ in valid_languages}
    code_by_header = {header: code for header, code in valid_languages}
    valid_codes: dict[str, str] = {}
    for _, code in valid_languages:
        valid_codes.setdefault(code, CANONICAL_LANGUAGE_HEADER[code])
    if not languages:
        return [header for header, _ in valid_languages]

    selected: list[str] = []
    for lang in languages:
        raw = str(lang).strip()
        if raw in valid_headers:
            selected.append(CANONICAL_LANGUAGE_HEADER[code_by_header[raw]])
            continue
        code = raw.lower()
        if code in valid_codes:
            selected.append(valid_codes[code])
            continue
        normalized = raw.upper()
        if normalized in valid_headers:
            selected.append(CANONICAL_LANGUAGE_HEADER[code_by_header[normalized]])
            continue
        raise ValueError(f"unsupported language: {lang}")
    return selected


def _manifest_languages(manifest: dict[str, Any]) -> list[tuple[str, str]]:
    languages = []
    for item in manifest.get("languages", []):
        header = str(item.get("header", "")).strip().upper()
        code = str(item.get("code", "")).strip()
        if header and code:
            languages.append((header, code))
    return languages or list(TARGET_LANGUAGES)


def _expected_paragraphs(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    expected: dict[str, dict[str, Any]] = {}
    for doc in manifest.get("documents", []):
        for row in doc.get("paragraphs", []):
            expected[str(row["para_id"])] = row
    return expected


def _ordered_expected_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    for doc in manifest.get("documents", []):
        ordered.extend(doc.get("paragraphs", []))
    return ordered


def _load_manifest(work_dir: Path) -> dict[str, Any]:
    path = work_dir / MANIFEST_NAME
    if not path.exists():
        raise ValueError(f"manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _work_dir(input_dir: Path) -> Path:
    return input_dir / WORK_DIR_NAME / HARNESS_DIR_NAME


def _language_code_for_header(header: str) -> str:
    return LANGUAGE_CODE_BY_HEADER.get(str(header or "").strip().upper(), "")


def _is_temp_file(path: Path) -> bool:
    return path.name.startswith("~$")


def _is_generated_docx(path: Path) -> bool:
    stem = path.stem.lower()
    generated_suffixes = {f"_{code}" for _, code in SUPPORTED_LANGUAGES}
    generated_suffixes.update(f"_{header.lower()}" for header, _ in SUPPORTED_LANGUAGES)
    return any(stem.endswith(suffix) for suffix in generated_suffixes)


def _clean_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _parse_json_cell(value: Any, default: Any) -> Any:
    text = _clean_cell(value)
    if not text:
        return default
    return json.loads(text)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
