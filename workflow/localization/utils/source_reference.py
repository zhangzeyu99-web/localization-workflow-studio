"""Source-language mode and English-reference extraction for language tables."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

import pandas as pd

from utils.excel_reader import resolve_language_index
from utils.language_config import normalize_language_code


SOURCE_MODES = ("cn", "cn+en", "en")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")


@dataclass(frozen=True)
class EnglishReferenceValue:
    text: str
    status: str


@dataclass(frozen=True)
class EnglishReferenceStatus:
    column: str
    total_rows: int
    usable_rows: int
    empty_rows: int
    chinese_rows: int

    @property
    def coverage(self) -> float:
        if self.total_rows == 0:
            return 0.0
        return round(self.usable_rows / self.total_rows, 4)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "coverage": self.coverage}


def normalize_source_mode(source_mode: str | None) -> str:
    mode = str(source_mode or "cn").strip().lower()
    if mode not in SOURCE_MODES:
        raise ValueError(f"source_mode must be one of: {', '.join(SOURCE_MODES)}")
    return mode


def _clean_reference(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def classify_english_reference(value: Any) -> EnglishReferenceValue:
    text = _clean_reference(value)
    if not text:
        return EnglishReferenceValue(text="", status="missing")
    if _CJK_RE.search(text):
        return EnglishReferenceValue(text="", status="chinese_seed")
    return EnglishReferenceValue(text=text, status="usable")


def collect_english_references(
    df: pd.DataFrame,
    column_map: dict,
    row_indexes: Iterable[Any],
    *,
    target_lang: str,
    source_mode: str,
) -> tuple[dict[Any, EnglishReferenceValue], EnglishReferenceStatus | None]:
    """Collect row-aligned English references for cn+en/en modes."""
    mode = normalize_source_mode(source_mode)
    if mode == "cn":
        return {}, None
    if normalize_language_code(target_lang) == "en":
        raise ValueError("source_mode cn+en/en requires a non-English target language")

    try:
        english_index = resolve_language_index(column_map, "en", None)
    except (IndexError, ValueError) as exc:
        raise ValueError("source_mode cn+en/en requires an English reference column") from exc
    english_column = column_map["languages"][english_index]["translation_col"]

    references: dict[Any, EnglishReferenceValue] = {}
    usable_rows = 0
    empty_rows = 0
    chinese_rows = 0
    indexes = list(row_indexes)
    for index in indexes:
        reference = classify_english_reference(df.at[index, english_column])
        if reference.status == "missing":
            empty_rows += 1
        elif reference.status == "chinese_seed":
            chinese_rows += 1
        else:
            usable_rows += 1
        references[index] = reference

    summary = EnglishReferenceStatus(
        column=str(english_column),
        total_rows=len(indexes),
        usable_rows=usable_rows,
        empty_rows=empty_rows,
        chinese_rows=chinese_rows,
    )
    if mode == "en" and usable_rows != len(indexes):
        raise ValueError(
            "source_mode en requires complete usable English for every row: "
            f"usable={usable_rows}, missing={empty_rows}, chinese_seed={chinese_rows}"
        )
    return references, summary
