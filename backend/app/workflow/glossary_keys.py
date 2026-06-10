from __future__ import annotations

import re
from typing import Any


def _glossary_source_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).casefold()


def _glossary_term_rank(term: dict[str, Any]) -> tuple[int, int, int]:
    has_translation = bool(str(term.get("target") or "").strip() or str(term.get("target_alt") or "").strip())
    confirmed = bool(term.get("confirmed"))
    curated_source = str(term.get("source_type") or "") in {"manual", "imported", "curated"}
    return (0 if confirmed else 1, 0 if has_translation else 1, 0 if curated_source else 1)


def _fill_blank_glossary_fields(base: dict[str, Any], incoming: dict[str, Any]) -> None:
    for field in ("target", "target_alt", "category", "note"):
        if not str(base.get(field) or "").strip() and str(incoming.get(field) or "").strip():
            base[field] = incoming.get(field, "")
