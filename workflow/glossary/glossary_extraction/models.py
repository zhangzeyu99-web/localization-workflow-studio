"""Core data models shared across the glossary extraction workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Record:
    row_id: str
    source: str
    target: str
    sheet_name: str = field(default="", compare=False)
    row_number: int = field(default=0, compare=False)
    source_field: str = field(default="", compare=False)
    term_type_hint: str = field(default="", compare=False)


@dataclass
class SheetColumnLayout:
    header_row_index: int
    headers: list[str]
    id_index: int | None
    source_index: int
    target_index: int | None
    output_indexes: list[int | None]


@dataclass
class LanguageTableSpec:
    language: str
    path: Path
