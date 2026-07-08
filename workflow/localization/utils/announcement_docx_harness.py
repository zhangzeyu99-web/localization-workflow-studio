"""DOCX announcement translation harness.

This harness turns paragraph-only announcement DOCX files into a structured
translation workbook, validates terminology-constrained translations, and writes
language-specific DOCX copies back from stable paragraph IDs.

Implementation detail: the logic is split across
utils/announcement_docx_common.py (shared constants and helpers),
utils/announcement_docx_terms.py (term loading and hit extraction),
utils/announcement_docx_prepare.py (inspect/stage/prepare), and
utils/announcement_docx_apply.py (import/apply/deliver). This module
re-exports those symbols so existing
`from utils.announcement_docx_harness import ...` imports keep working.
"""
from __future__ import annotations

from utils.announcement_docx_common import (  # noqa: F401  (re-exported)
    AI_RESPONSE_PREFIX,
    CANONICAL_LANGUAGE_HEADER,
    FIXED_COLUMNS,
    HARNESS_DIR_NAME,
    LANGUAGE_CODE_BY_HEADER,
    MANIFEST_NAME,
    QA_SUMMARY_NAME,
    SUPPORTED_LANGUAGES,
    TARGET_LANGUAGES,
    TRANSLATION_WORKBOOK_NAME,
    WORK_DIR_NAME,
    _CJK_RE,
    _clean_cell,
    _expected_paragraphs,
    _is_generated_docx,
    _is_temp_file,
    _language_code_for_header,
    _load_manifest,
    _manifest_languages,
    _ordered_expected_rows,
    _parse_json_cell,
    _resolve_language_headers,
    _resolve_language_pairs,
    _sha256_file,
    _work_dir,
    _write_jsonl,
)
from utils.announcement_docx_terms import (  # noqa: F401  (re-exported)
    AnnouncementTerms,
    LanguageSpec,
    TermEntry,
    _find_term_hits,
    _is_low_value_announcement_term,
    _language_specs_from_headers,
    _read_announcement_language_specs,
    _term_occurs,
    load_announcement_terms,
)
from utils.announcement_docx_prepare import (  # noqa: F401  (re-exported)
    AnnouncementTaskInspection,
    PreparedAnnouncementHarness,
    StagedAnnouncementTask,
    _convert_txt_to_docx,
    _extract_date_stamp,
    _infer_language_pairs_from_terms,
    _inspect_unsupported,
    _is_loose_announcement_terms_file,
    _paragraph_id,
    _protected_tokens,
    _select_term_file_for_source,
    discover_announcement_docx_pairs,
    inspect_announcement_task_dir,
    prepare_announcement_docx_harness,
    stage_announcement_task_dir,
)
from utils.announcement_docx_apply import (  # noqa: F401  (re-exported)
    AppliedAnnouncementHarness,
    DeliveredAnnouncementOutputs,
    ImportedAnnouncementResponses,
    _contains_term,
    _read_ai_response_rows,
    _read_translation_rows,
    _replace_paragraph_text,
    _validate_all_translations,
    _validate_input_drift,
    _validate_row_coverage,
    _validate_translation,
    _write_ai_responses_to_workbook,
    _write_output_docx,
    _write_qa_summary,
    apply_announcement_translations,
    deliver_announcement_outputs,
    import_announcement_ai_responses,
)
