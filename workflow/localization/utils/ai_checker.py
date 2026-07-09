"""AI review helpers for prompt generation, response parsing, and strict merge."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from utils.language_config import LANGUAGE_NAMES, language_name

REVIEW_PROTOCOL_VERSION = 2

LANG_NAMES = {
    code: name
    for code, name in LANGUAGE_NAMES.items()
}


def _make_prompt_header(lang: str = "en") -> str:
    lang_name = language_name(lang)
    neutral = (
        f"You are reviewing {lang_name} game localization.\n"
        "Check each row for meaning errors, missing content, unnatural style, and term compliance.\n"
        "Keep placeholders, variables, BBCode, and line breaks exactly as needed.\n"
    )
    if lang == "ja":
        neutral += (
            "Japanese may naturally contain Kanji; do not treat Kanji itself as Chinese residue.\n"
            "Flag obvious Simplified Chinese leftovers, mixed-language mistranslations, and unnatural Japanese UI wording.\n"
        )
    elif lang == "ko":
        neutral += (
            "Korean output should be natural Korean; flag Hangul-missing translations, obvious Chinese leftovers, and untranslated source fragments.\n"
        )

    english_rules = ""
    if lang == "en":
        english_rules = (
        "Do not invent opaque abbreviations or internal-code style UI text, such as PERR, DTT, IDNE, IJA, or CL##1##2.\n"
        "Do not shorten text by clipping words, dropping vowels, or truncating fragments, such as rewa, obta, coll imme, or tmrw.\n"
        "Do not abbreviate profession, resource, item, skill, shop, search-result, message, mail, capacity, content, contribution, placement, or equipment words into fragments such as Doct, Ener Scie, Stru Expe, Smel Expe, Pts impr esse, Res., No sear resu, Fast Trac Bull, Fina ATK SPD, Repl This mess expi, No unre mess, Hara swip spam mess, Troo capa, Conf spen ##1 diam, Figh modi leve ##1, Offline Rwds, Inte guid, Glor Cont, Cont cann empt, Your cont ##1, Loca cann plac, Wear equi cann rese, No wear equi, or Stro equi Pack.\n"
        "Do not leave romanized Chinese-name residue in English rows when a natural localized name is needed, such as Chef Yifang.\n"
        "Allowed stable game abbreviations include HP, ATK, DEF, DMG, DPS, PVP, PVE, VIP, FPS, SFX, UI, and Lv.\n"
        "Use sentence case by default for English status, error, and prompt text; reserve Title Case for proper names, feature names, headings, and glossary-approved terms.\n"
        )

    return (
        neutral
        + english_rules
        +
        "\n"
        "Output protocol (mandatory):\n"
        "- Cover every ID in this batch exactly once.\n"
        "- Keep the same ID order as the input list.\n"
        "- If current translation is fine: ID | KEEP\n"
        "- If it needs correction: ID | FIX | corrected translation\n"
        "- Do not omit any ID.\n"
        "- Do not output explanations, headings, summaries, or code fences.\n"
        "\n"
    )


def _make_ui_length_section() -> str:
    return (
        "Short-text length rule for Chinese source text with 10 or fewer characters:\n"
        "- Keep the translation natural and easy to understand.\n"
        "- If LEN mode is hard, treat the budget as a display guardrail, not a reason to over-compress normal words.\n"
        "- If LEN mode is soft, prefer a shorter option, but keep clarity first.\n"
        "- English may be slightly longer than Chinese, but avoid obvious length expansion.\n"
        "- If LEN metadata is present, use the budget as a guide and only exceed it when clarity clearly requires it.\n"
        "- If compactness conflicts with readability, choose the readable translation; never use opaque abbreviations or clipped words to fit the budget.\n"
        "\n"
    )


def _make_term_section(lang: str = "en", has_constraints: bool = False) -> str:
    lang_name = language_name(lang)
    header_cols = (
        "Source term | Primary target | Accepted variants | Constraint"
        if has_constraints
        else "Source term | Primary target | Accepted variants"
    )
    extra = (
        "- If a term has a constraint, only use the listed term forms.\n"
        if has_constraints
        else ""
    )
    return (
        f"Relevant terminology for this {lang_name} batch:\n"
        "- Matching the primary term or an accepted variant counts as correct.\n"
        "- Case is not enforced unless the term says otherwise.\n"
        f"{extra}"
        f"\n{header_cols}\n"
        "{{term_lines}}\n\n"
    )


@dataclass
class AICorrection:
    """A single correction produced by AI review."""

    row_id: int
    corrected_translation: str


@dataclass
class ReviewDecision:
    """One exhaustive AI review line."""

    row_id: int
    action: str
    corrected_translation: str = ""


@dataclass
class BatchInfo:
    """Metadata for one review batch."""

    batch_num: int
    total_batches: int
    row_ids: list[int] = field(default_factory=list)
    prompt_text: str = ""
    response_text: str = ""
    corrections: list[AICorrection] = field(default_factory=list)
    is_done: bool = False


def split_into_batches(rows: list[dict], batch_size: int = 200) -> list[list[dict]]:
    """Split rows into fixed-size batches."""

    return [rows[i : i + batch_size] for i in range(0, len(rows), batch_size)]


def _extract_relevant_terms(
    batch_rows: list[dict],
    term_lookup: dict | None,
    max_terms: int = 120,
) -> list[tuple[str, str, str, str]]:
    if not term_lookup:
        return []

    combined_originals = " ".join(str(r["original"]) for r in batch_rows)
    hits: list[tuple[str, str, str, str, int]] = []
    for cn_term, term_item in term_lookup.items():
        if isinstance(term_item, dict):
            primary = str(term_item.get("primary", "")).strip()
            variants = term_item.get("variants", [])
            if isinstance(variants, str):
                variants = [variants]
            variants = [str(x).strip() for x in variants if str(x).strip()]
            variant_text = " / ".join(variants) if variants else "-"
            constraint = str(term_item.get("constraint", "")).strip()
            if constraint.lower() == "nan":
                constraint = ""
        else:
            primary = str(term_item).strip()
            variant_text = "-"
            constraint = ""
        count = combined_originals.count(cn_term)
        if count > 0:
            hits.append((cn_term, primary, variant_text, constraint, count))

    hits.sort(key=lambda item: (-item[4], -len(item[0])))
    return [(cn, primary, variants, constraint) for cn, primary, variants, constraint, _ in hits[:max_terms]]


def _make_term_priority_section(batch_rows: list[dict]) -> str:
    flagged_rows = [row for row in batch_rows if str(row.get("term_status", "")) == "TERM_ERROR"]
    if not flagged_rows:
        return ""

    lines = []
    for row in flagged_rows[:120]:
        row_id = row["id"]
        original = str(row["original"]).replace("\n", "\\n")
        translation = str(row["translation"]).replace("\n", "\\n")
        issue_types = str(row.get("term_issue_types", "")).strip() or "-"
        ui_flag = "yes" if row.get("is_ui") else "no"
        lines.append(f"{row_id} | {original} | {translation} | {issue_types} | UI:{ui_flag}")

    return (
        "Priority rows flagged by machine review for terminology problems:\n"
        "ID | Source | Current translation | Term issue types | UI\n"
        + "\n".join(lines)
        + "\n\n"
    )


def format_batch_prompt(
    batch_rows: list[dict],
    batch_num: int,
    total_batches: int,
    term_lookup: dict | None = None,
    lang: str = "en",
    max_terms: int = 120,
) -> str:
    """Generate the AI review prompt for one batch."""

    prompt = _make_prompt_header(lang)
    if any("ui_length_budget" in row for row in batch_rows):
        prompt += _make_ui_length_section()
    relevant_terms = _extract_relevant_terms(batch_rows, term_lookup, max_terms=max_terms)
    if relevant_terms:
        has_constraints = any(constraint for _, _, _, constraint in relevant_terms)
        term_lines = []
        for cn_term, primary, variants, constraint in relevant_terms:
            if constraint:
                term_lines.append(f"{cn_term} | {primary} | {variants} | {constraint}")
            elif has_constraints:
                term_lines.append(f"{cn_term} | {primary} | {variants} |")
            else:
                term_lines.append(f"{cn_term} | {primary} | {variants}")
        prompt += _make_term_section(lang, has_constraints=has_constraints).replace(
            "{{term_lines}}",
            "\n".join(term_lines),
        )

    if any("term_status" in row for row in batch_rows):
        prompt += _make_term_priority_section(batch_rows)

    lines = []
    has_ui_meta = any("is_ui" in row for row in batch_rows)
    has_len_meta = any("ui_length_budget" in row for row in batch_rows)
    for row in batch_rows:
        row_id = row["id"]
        original = str(row["original"]).replace("\n", "\\n")
        translation = str(row["translation"]).replace("\n", "\\n")
        meta = []
        if has_ui_meta:
            ui_flag = "yes" if row.get("is_ui") else "no"
            meta.append(f"UI:{ui_flag}")
        if has_len_meta:
            if "ui_length_budget" in row:
                meta.append(
                    "LEN:"
                    f"mode={row.get('ui_length_policy', 'hard')},"
                    f"source={row.get('ui_length_source_len', 0)},"
                    f"target={row.get('ui_length_target_len', 0)},"
                    f"budget<={row.get('ui_length_budget', 0)}"
                )
            else:
                meta.append("LEN:-")
        if meta:
            lines.append(f"{row_id} | {original} | {translation} | " + " | ".join(meta))
        else:
            lines.append(f"{row_id} | {original} | {translation}")

    header = "ID | Source | Translation"
    if has_ui_meta:
        header += " | UI"
    if has_len_meta:
        header += " | LEN"
    prompt += (
        f"Rows to review (batch {batch_num}/{total_batches}):\n\n"
        + header
        + "\n"
        + "\n".join(lines)
    )
    return prompt


def prepare_all_batches(
    rows: list[dict],
    batch_size: int = 200,
    term_lookup: dict | None = None,
    lang: str = "en",
    max_terms: int = 120,
) -> list[BatchInfo]:
    """Prepare all main review batches."""

    chunks = split_into_batches(rows, batch_size)
    total_batches = len(chunks)
    batches = []
    for index, chunk in enumerate(chunks, start=1):
        batch = BatchInfo(
            batch_num=index,
            total_batches=total_batches,
            row_ids=[row["id"] for row in chunk],
        )
        batch.prompt_text = format_batch_prompt(
            chunk,
            index,
            total_batches,
            term_lookup=term_lookup,
            lang=lang,
            max_terms=max_terms,
        )
        batches.append(batch)
    return batches


def format_recheck_prompt(
    batch_rows: list[dict],
    batch_num: int,
    total_batches: int,
    term_lookup: dict | None = None,
    lang: str = "en",
    max_terms: int = 120,
) -> str:
    """Generate focused recheck prompt for unresolved term issues."""

    prompt = (
        f"Second-pass terminology review for {language_name(lang)} localization.\n"
        "These rows still need term compliance confirmation.\n"
        "\n"
        "Output protocol (mandatory):\n"
        "- Cover every ID in this batch exactly once.\n"
        "- Keep the same ID order as the input list.\n"
        "- If current translation is fine: ID | KEEP\n"
        "- If it needs correction: ID | FIX | corrected translation\n"
        "- Do not omit any ID.\n"
        "- Do not output explanations, headings, summaries, or code fences.\n"
        "\n"
    )
    if any("ui_length_budget" in row for row in batch_rows):
        prompt += _make_ui_length_section()

    relevant_terms = _extract_relevant_terms(batch_rows, term_lookup, max_terms=max_terms)
    if relevant_terms:
        has_constraints = any(constraint for _, _, _, constraint in relevant_terms)
        term_lines = []
        for cn_term, primary, variants, constraint in relevant_terms:
            if constraint:
                term_lines.append(f"{cn_term} | {primary} | {variants} | {constraint}")
            elif has_constraints:
                term_lines.append(f"{cn_term} | {primary} | {variants} |")
            else:
                term_lines.append(f"{cn_term} | {primary} | {variants}")
        prompt += _make_term_section(lang, has_constraints=has_constraints).replace(
            "{{term_lines}}",
            "\n".join(term_lines),
        )

    lines = []
    has_len_meta = any("ui_length_budget" in row for row in batch_rows)
    for row in batch_rows:
        row_id = row["id"]
        original = str(row["original"]).replace("\n", "\\n")
        translation = str(row["translation"]).replace("\n", "\\n")
        issue = str(row.get("term_issue", "")).replace("\n", " ")
        if has_len_meta and "ui_length_budget" in row:
            len_meta = (
                "LEN:"
                f"mode={row.get('ui_length_policy', 'hard')},"
                f"source={row.get('ui_length_source_len', 0)},"
                f"target={row.get('ui_length_target_len', 0)},"
                f"budget<={row.get('ui_length_budget', 0)}"
            )
            lines.append(f"{row_id} | {original} | {translation} | {issue} | {len_meta}")
        else:
            lines.append(f"{row_id} | {original} | {translation} | {issue}")

    prompt += (
        f"Rows to recheck (batch {batch_num}/{total_batches}):\n\n"
        + ("ID | Source | Translation | Term issue | LEN\n" if has_len_meta else "ID | Source | Translation | Term issue\n")
        + "\n".join(lines)
    )
    return prompt


def prepare_recheck_batches(
    rows: list[dict],
    batch_size: int = 500,
    term_lookup: dict | None = None,
    lang: str = "en",
    max_terms: int = 120,
) -> list[BatchInfo]:
    """Prepare all recheck batches."""

    chunks = split_into_batches(rows, batch_size)
    total_batches = len(chunks)
    batches = []
    for index, chunk in enumerate(chunks, start=1):
        batch = BatchInfo(
            batch_num=index,
            total_batches=total_batches,
            row_ids=[row["id"] for row in chunk],
        )
        batch.prompt_text = format_recheck_prompt(
            chunk,
            index,
            total_batches,
            term_lookup=term_lookup,
            lang=lang,
            max_terms=max_terms,
        )
        batches.append(batch)
    return batches


_LEGACY_CORRECTION_PATTERN = re.compile(r"^\s*(\d+)\s*\|\s*(.+?)\s*$", re.MULTILINE)
_KEEP_PATTERN = re.compile(r"^\s*(\d+)\s*\|\s*(KEEP|OK)\s*$", re.IGNORECASE)
_FIX_PATTERN = re.compile(r"^\s*(\d+)\s*\|\s*(FIX|CHANGE)\s*\|\s*(.+?)\s*$", re.IGNORECASE)


def _strip_code_fences(response_text: str) -> list[str]:
    lines = []
    for raw_line in response_text.splitlines():
        if raw_line.strip().startswith("```"):
            continue
        lines.append(raw_line.rstrip())
    return lines


def parse_review_response(response_text: str, strict: bool = False) -> dict[int, ReviewDecision]:
    """Parse exhaustive response lines.

    Strict mode only accepts:
      ID | KEEP
      ID | FIX | corrected translation
    Non-strict mode also accepts the legacy:
      ID | corrected translation
    """

    if not response_text:
        return {}

    decisions: dict[int, ReviewDecision] = {}
    invalid_lines: list[str] = []
    for raw_line in _strip_code_fences(response_text):
        line = raw_line.strip()
        if not line:
            continue

        keep_match = _KEEP_PATTERN.match(line)
        if keep_match:
            row_id = int(keep_match.group(1))
            decisions[row_id] = ReviewDecision(row_id=row_id, action="KEEP")
            continue

        fix_match = _FIX_PATTERN.match(line)
        if fix_match:
            row_id = int(fix_match.group(1))
            decisions[row_id] = ReviewDecision(
                row_id=row_id,
                action="FIX",
                corrected_translation=fix_match.group(3).strip(),
            )
            continue

        if not strict:
            legacy_match = _LEGACY_CORRECTION_PATTERN.match(line)
            if legacy_match:
                row_id = int(legacy_match.group(1))
                decisions[row_id] = ReviewDecision(
                    row_id=row_id,
                    action="FIX",
                    corrected_translation=legacy_match.group(2).strip(),
                )
                continue

        invalid_lines.append(line)

    if strict and invalid_lines:
        raise ValueError("AI response contains invalid lines: " + " | ".join(invalid_lines[:5]))
    return decisions


def parse_ai_response(response_text: str) -> list[AICorrection]:
    """Parse response into corrections only.

    Supports both legacy 'ID | corrected translation' and strict protocol lines.
    """

    decisions = parse_review_response(response_text, strict=False)
    corrections = []
    for decision in decisions.values():
        if decision.action != "FIX":
            continue
        if decision.corrected_translation:
            corrections.append(
                AICorrection(
                    row_id=decision.row_id,
                    corrected_translation=decision.corrected_translation,
                )
            )
    return corrections


def apply_corrections(corrections: list[AICorrection], states: dict) -> int:
    """Apply AI corrections to RowState objects."""

    modified = 0
    for correction in corrections:
        state = states.get(correction.row_id)
        if not state:
            continue
        if state.fixed_translation != correction.corrected_translation:
            state.fixed_translation = correction.corrected_translation
            state.notes.append("AI审校修正")
            modified += 1
    return modified


def build_row_fingerprint(row_id: int, original: str, translation: str) -> str:
    payload = json.dumps(
        {
            "row_id": row_id,
            "original": original,
            "translation": translation,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _batch_file_stem(batch_type: str, batch_num: int) -> str:
    prefix = "batch_recheck" if batch_type == "recheck" else "batch"
    return f"{prefix}_{batch_num}"


def _build_batch_manifest(
    batch: BatchInfo,
    states: dict,
    *,
    batch_type: str,
    lang: str,
    input_path: str,
    ai_scope: str,
) -> dict:
    rows = []
    for row_id in batch.row_ids:
        state = states.get(row_id)
        if state is None:
            raise KeyError(f"Unknown row id in batch manifest: {row_id}")
        rows.append(
            {
                "id": row_id,
                "fingerprint": build_row_fingerprint(
                    row_id,
                    str(state.original),
                    str(state.fixed_translation),
                ),
            }
        )

    file_stem = _batch_file_stem(batch_type, batch.batch_num)
    return {
        "protocol_version": REVIEW_PROTOCOL_VERSION,
        "batch_num": batch.batch_num,
        "batch_type": batch_type,
        "lang": lang,
        "input_path": input_path,
        "ai_scope": ai_scope,
        "row_count": len(rows),
        "rows": rows,
        "prompt_file": f"{file_stem}.txt",
        "response_file": f"{file_stem}_response.txt",
    }


def reset_review_dir(review_dir: Path) -> None:
    """Remove stale review batch/manifest files before a new review run."""
    review_dir.mkdir(parents=True, exist_ok=True)
    for pattern in (
        'batch_*.txt',
        'batch_*.json',
        'batch_*_response.txt',
        'batch_recheck_*.txt',
        'batch_recheck_*.json',
        'batch_recheck_*_response.txt',
        'review_run_manifest.json',
        'review_recheck_manifest.json',
    ):
        for path in review_dir.glob(pattern):
            path.unlink()


def collect_recheck_rows(states, batches) -> list[dict]:
    """Collect rows from AI batches that still carry term issues for recheck."""
    term_error_types = {'term_missing', 'term_partial_hit', 'term_capitalization'}
    recheck_rows = []
    ai_batch_ids = set()
    for batch in batches:
        ai_batch_ids.update(batch.row_ids)

    for state in states.values():
        if state.row_id not in ai_batch_ids:
            continue
        has_term_issue = any(getattr(issue, 'check_type', '') in term_error_types for issue in state.issues)
        if not has_term_issue:
            continue
        issue_desc = '; '.join(sorted(set(
            getattr(issue, 'check_type', '')
            for issue in state.issues
            if getattr(issue, 'check_type', '') in term_error_types
        )))
        recheck_rows.append(
            {
                'id': state.row_id,
                'original': state.original,
                'translation': state.fixed_translation,
                'term_issue': issue_desc,
            }
        )
    return recheck_rows


def write_review_files(
    review_dir: str | Path,
    batches: list[BatchInfo],
    states: dict,
    *,
    batch_type: str,
    lang: str,
    input_path: str,
    ai_scope: str,
) -> Path:
    """Write prompts plus strict manifest files for one review stage."""

    review_root = Path(review_dir)
    review_root.mkdir(parents=True, exist_ok=True)

    dataset_fingerprints: list[str] = []
    batch_refs = []
    for batch in batches:
        file_stem = _batch_file_stem(batch_type, batch.batch_num)
        prompt_path = review_root / f"{file_stem}.txt"
        prompt_path.write_text(batch.prompt_text, encoding="utf-8")

        manifest = _build_batch_manifest(
            batch,
            states,
            batch_type=batch_type,
            lang=lang,
            input_path=input_path,
            ai_scope=ai_scope,
        )
        manifest_path = review_root / f"{file_stem}.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        dataset_fingerprints.extend(row["fingerprint"] for row in manifest["rows"])
        batch_refs.append(
            {
                "batch_num": batch.batch_num,
                "manifest_file": manifest_path.name,
                "prompt_file": manifest["prompt_file"],
                "response_file": manifest["response_file"],
                "row_count": manifest["row_count"],
            }
        )

    run_manifest = {
        "protocol_version": REVIEW_PROTOCOL_VERSION,
        "batch_type": batch_type,
        "lang": lang,
        "input_path": input_path,
        "ai_scope": ai_scope,
        "total_batches": len(batches),
        "total_rows": sum(len(batch.row_ids) for batch in batches),
        "dataset_fingerprint": hashlib.sha256(
            "|".join(dataset_fingerprints).encode("utf-8")
        ).hexdigest(),
        "batches": batch_refs,
    }
    manifest_name = "review_recheck_manifest.json" if batch_type == "recheck" else "review_run_manifest.json"
    manifest_path = review_root / manifest_name
    manifest_path.write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_path


def _expected_batch_manifest_paths(review_dir: Path, batch_type: str) -> list[Path]:
    if batch_type == "recheck":
        return sorted(review_dir.glob("batch_recheck_*.json"))
    return sorted(
        path for path in review_dir.glob("batch_*.json")
        if not path.name.startswith("batch_recheck_")
    )


def write_response_templates(
    review_dir: str | Path,
    *,
    batch_type: str = "main",
    overwrite: bool = False,
) -> int:
    """Seed exhaustive response files with default KEEP lines.

    This guarantees full-ID coverage before any AI editing starts.
    """

    review_root = Path(review_dir)
    created = 0
    for manifest_path in _expected_batch_manifest_paths(review_root, batch_type):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        response_path = review_root / manifest["response_file"]
        if response_path.exists() and not overwrite:
            continue
        lines = [f"{int(row['id'])} | KEEP" for row in manifest["rows"]]
        response_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        created += 1
    return created


def merge_review_batches(
    review_dir: str | Path,
    states: dict,
    *,
    batch_type: str = "main",
    strict: bool = True,
    ignore_fingerprint_for: set[int] | None = None,
) -> tuple[set[int], set[int], list[dict]]:
    """Merge strict review responses back into current states."""

    review_root = Path(review_dir)
    manifest_paths = _expected_batch_manifest_paths(review_root, batch_type)
    if not manifest_paths:
        return set(), set(), []

    reviewed_ids: set[int] = set()
    corrected_ids: set[int] = set()
    summaries: list[dict] = []
    ignore_fingerprint_for = ignore_fingerprint_for or set()

    for manifest_path in manifest_paths:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        response_path = review_root / manifest["response_file"]
        if not response_path.exists():
            if strict:
                raise ValueError(f"Missing AI response file: {response_path.name}")
            continue

        expected_ids = []
        for row in manifest["rows"]:
            row_id = int(row["id"])
            state = states.get(row_id)
            if state is None:
                raise ValueError(f"Row {row_id} no longer exists for merge")
            current_fingerprint = build_row_fingerprint(
                row_id,
                str(state.original),
                str(state.fixed_translation),
            )
            if current_fingerprint != row["fingerprint"] and row_id not in ignore_fingerprint_for:
                raise ValueError(
                    f"Input drift detected before merge in {manifest_path.name} for row {row_id}"
                )
            expected_ids.append(row_id)

        decisions = parse_review_response(
            response_path.read_text(encoding="utf-8"),
            strict=strict,
        )
        actual_ids = list(decisions.keys())
        if strict and actual_ids != expected_ids:
            raise ValueError(
                f"AI response coverage mismatch in {response_path.name}: "
                f"expected {len(expected_ids)} ids, got {len(actual_ids)}"
            )

        corrections = [
            AICorrection(
                row_id=decision.row_id,
                corrected_translation=decision.corrected_translation,
            )
            for decision in decisions.values()
            if decision.action == "FIX"
        ]
        modified = apply_corrections(corrections, states)

        reviewed_ids.update(expected_ids if strict else decisions.keys())
        corrected_ids.update(correction.row_id for correction in corrections)
        summaries.append(
            {
                "batch_name": manifest_path.stem,
                "expected_rows": len(expected_ids),
                "reviewed_rows": len(actual_ids),
                "corrections": len(corrections),
                "modified": modified,
            }
        )

    return reviewed_ids, corrected_ids, summaries


class AIChecker:
    """Base class for future direct API integrations."""

    def check_batch(self, rows: list[dict], term_lookup: dict[str, str] | None = None) -> list[AICorrection]:
        raise NotImplementedError


class DummyAIChecker(AIChecker):
    """No-op placeholder."""

    def check_batch(self, rows, term_lookup=None):
        return []
