"""Conservative local repair for deterministic CJK residue."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


CJK_RE = re.compile(r"[\u3400-\u9fff]")
CHAPTER_NUMBER_RE = re.compile(
    r"(?P<prefix>(?:Chapter|Chapitre|Kapitel|Cap[ií]tulo|Capitolo|Bölüm|Глава|Bab|Chương|บทที่|الفصل)\s*)"
    r"(?P<number>[一二三四五六七八九十]+)",
    re.IGNORECASE,
)
CHINESE_CHAPTER_RE = re.compile(r"第(?P<number>[一二三四五六七八九十]+)章")
CHAPTER_WORDS = {
    "EN": "Chapter",
    "DE": "Kapitel",
    "FR": "Chapitre",
    "ES": "Capítulo",
    "PT": "Capítulo",
    "IT": "Capitolo",
    "TR": "Bölüm",
    "TK": "Bölüm",
    "RU": "Глава",
    "ID": "Bab",
    "IDN": "Bab",
    "TH": "บทที่",
    "VI": "Chương",
    "AR": "الفصل",
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _chinese_number(value: str) -> int | None:
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if "十" in value:
        left, right = value.split("十", 1)
        tens = digits.get(left, 1) if left else 1
        ones = digits.get(right, 0) if right else 0
        return tens * 10 + ones
    return digits.get(value)


def _roman(value: int) -> str:
    pairs = (
        (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"),
        (4, "IV"), (1, "I"),
    )
    result: list[str] = []
    for number, numeral in pairs:
        while value >= number:
            result.append(numeral)
            value -= number
    return "".join(result)


def _term_target(hit: dict[str, Any], lang: str) -> str:
    translations = hit.get("translations")
    if isinstance(translations, dict) and translations.get(lang):
        return str(translations[lang]).strip()
    return str(hit.get(lang) or "").strip()


def repair_text(text: str, row: dict[str, Any], lang: str) -> tuple[str, list[str]]:
    if not CJK_RE.search(text):
        return text, []
    repaired = text
    reasons: list[str] = []
    hits = [hit for hit in (row.get("term_hits") or []) if isinstance(hit, dict)]
    for hit in sorted(
        hits,
        key=lambda item: len(str(item.get("source") or item.get("CN") or item.get("term") or "")),
        reverse=True,
    ):
        source = str(hit.get("source") or hit.get("CN") or hit.get("term") or "")
        target = _term_target(hit, lang)
        if source and source in repaired and target and not CJK_RE.search(target):
            repaired = repaired.replace(source, target)
            reasons.append(f"term:{source}")

    def replace_number(match: re.Match[str]) -> str:
        number = _chinese_number(match.group("number"))
        if number is None:
            return match.group(0)
        reasons.append(f"chapter-number:{match.group('number')}")
        return match.group("prefix") + _roman(number)

    repaired = CHAPTER_NUMBER_RE.sub(replace_number, repaired)

    chapter_word = CHAPTER_WORDS.get(lang)
    if chapter_word:
        def replace_chapter(match: re.Match[str]) -> str:
            number = _chinese_number(match.group("number"))
            if number is None:
                return match.group(0)
            reasons.append(f"chapter:{match.group('number')}")
            return f"{chapter_word} {_roman(number)}"

        repaired = CHINESE_CHAPTER_RE.sub(replace_chapter, repaired)
    return repaired, reasons


def repair_cache_residue(
    cache_jsonl: Path,
    *,
    target_langs: list[str],
    report_path: Path,
) -> dict[str, Any]:
    rows = _read_jsonl(cache_jsonl)
    changes: list[dict[str, Any]] = []
    for row in rows:
        translations = dict(row.get("translations") or {})
        for lang in target_langs:
            before = str(translations.get(lang) or "")
            after, reasons = repair_text(before, row, lang)
            if after == before:
                continue
            translations[lang] = after
            changes.append(
                {
                    "key": row.get("key"),
                    "lang": lang,
                    "before": before,
                    "after": after,
                    "reasons": reasons,
                }
            )
        row["translations"] = translations
    if changes:
        _write_jsonl(cache_jsonl, rows)
    report = {"changed_cells": len(changes), "changes": changes}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
