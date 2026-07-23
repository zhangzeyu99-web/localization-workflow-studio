"""Core data models shared across the glossary extraction workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Record:
    row_id: str
    source: str
    target: str


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
