"""Row state tracking and machine-review check phases for the main processing script.

Implementation module split out of process_language.py. Import these symbols
through process_language to keep the public surface stable.
"""
import re

import pandas as pd

from utils.variable_checker import check_all as check_variables
from utils.term_checker import check_term_hit, check_chinese_residue
from utils.pattern_detector import detect_patterns
from utils.ui_detector import is_ui_text
from utils.ai_checker import prepare_all_batches
from utils.text_normalize import repair_translation_surface
from utils.ui_length_checker import assess_ui_length, check_ui_length
from utils.readability_checker import check_readability


RowId = int | str


# ─────────────────────────────────────────────────────────────
# Row state tracker
# ─────────────────────────────────────────────────────────────

class RowState:
    __slots__ = (
        'row_id', 'original', 'translation', 'fixed_translation',
        'notes', 'is_ui', 'ui_confidence', 'issues',
        'needs_human_review', 'human_review_reason', 'ai_suggestion',
        'review_confidence',
        'short_text_length_policy', 'short_text_source_len',
        'short_text_target_len', 'short_text_budget',
    )

    def __init__(self, row_id: RowId, original: str, translation: str):
        self.row_id = row_id
        self.original = original
        self.translation = translation
        self.fixed_translation = translation
        self.notes: list[str] = []
        self.is_ui = False
        self.ui_confidence = 0.0
        self.issues: list = []
        self.needs_human_review = False
        self.human_review_reason = ''
        self.ai_suggestion = ''
        self.review_confidence = 1.0
        self.short_text_length_policy = ''
        self.short_text_source_len = 0
        self.short_text_target_len = 0
        self.short_text_budget = 0


def _coerce_row_id(value) -> RowId | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        text = str(value).strip()
        return text or None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else str(value).strip()
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r'-?(0|[1-9]\d*)', text):
        return int(text)
    return text


# ─────────────────────────────────────────────────────────────
# Check phases
# ─────────────────────────────────────────────────────────────

def _safe_apply_fix(state, new_translation: str, note: str):
    """Apply a fix only if it doesn't introduce Chinese residue or extra variables."""
    from utils.text_normalize import normalize_escapes, extract_vars
    from collections import Counter
    import re
    cn_pat = re.compile(r'[\u4e00-\u9fa5]')

    old_norm = normalize_escapes(state.fixed_translation)
    new_norm = normalize_escapes(new_translation)

    if cn_pat.search(new_norm) and not cn_pat.search(old_norm):
        return False

    orig_var_counts = Counter(extract_vars(state.original))
    new_var_counts = Counter(extract_vars(new_translation))
    if any(new_var_counts.get(v, 0) > orig_var_counts.get(v, 0) for v in new_var_counts):
        return False

    state.fixed_translation = new_translation
    state.notes.append(note)
    return True


def _run_variable_checks(states: dict[RowId, RowState], auto_fix: bool):
    for state in states.values():
        for r in check_variables(state.row_id, state.original, state.fixed_translation):
            state.issues.append(r)
            if auto_fix and r.auto_fix and r.severity == 'error':
                _safe_apply_fix(state, r.auto_fix, f"自动修复({r.check_type}): {r.message}")
            elif r.severity == 'error':
                state.needs_human_review = True
                state.human_review_reason = r.message
                state.ai_suggestion = r.auto_fix or state.fixed_translation
                state.review_confidence = r.confidence


def _run_surface_fixes(states: dict[RowId, RowState], auto_fix: bool, lang: str):
    for state in states.values():
        repaired = repair_translation_surface(state.original, state.fixed_translation, lang=lang)
        if repaired == state.fixed_translation:
            continue
        if auto_fix:
            _safe_apply_fix(state, repaired, "符号/占位符规范化")
        else:
            state.needs_human_review = True
            state.human_review_reason = "符号或占位符格式异常"
            state.ai_suggestion = repaired
            state.review_confidence = 0.95


def _run_term_checks(states: dict[RowId, RowState], term_lookup: dict, auto_fix: bool, lang: str):
    if not term_lookup:
        return
    for state in states.values():
        for r in check_term_hit(state.row_id, state.original, state.fixed_translation, term_lookup, lang=lang):
            state.issues.append(r)
            if auto_fix and r.auto_fix and r.confidence >= 0.8:
                _safe_apply_fix(state, r.auto_fix, f"术语修复: {r.message}")
            elif r.severity == 'error':
                state.needs_human_review = True
                state.human_review_reason = r.message
                state.ai_suggestion = r.auto_fix or state.fixed_translation
                state.review_confidence = r.confidence


def _run_chinese_residue_checks(states: dict[RowId, RowState], lang: str):
    for state in states.values():
        for r in check_chinese_residue(state.row_id, state.fixed_translation, lang=lang):
            state.issues.append(r)
            state.needs_human_review = True
            state.human_review_reason = r.message
            state.ai_suggestion = state.fixed_translation
            state.review_confidence = 0.5


def _run_pattern_checks(states: dict[RowId, RowState], auto_fix: bool):
    rows = [
        {'id': s.row_id, 'original': s.original, 'translation': s.fixed_translation}
        for s in states.values()
    ]
    groups, issues = detect_patterns(rows, min_group_size=3)

    for issue in issues:
        state = states.get(issue.row_id)
        if not state:
            continue
        state.issues.append(issue)

        if auto_fix and issue.auto_fix and issue.confidence >= 0.7:
            _safe_apply_fix(state, issue.auto_fix, f"句式统一: {issue.best_pattern[:50]}")
        elif issue.confidence >= 0.6:
            state.needs_human_review = True
            state.human_review_reason = issue.message
            state.ai_suggestion = issue.auto_fix or state.fixed_translation
            state.review_confidence = issue.confidence
        else:
            state.needs_human_review = True
            state.human_review_reason = (
                f"句式存疑(置信度{issue.confidence:.0%}): {issue.message}"
            )
            state.ai_suggestion = issue.auto_fix or state.fixed_translation
            state.review_confidence = issue.confidence

    return groups


def _run_ui_detection(states: dict[RowId, RowState]):
    for state in states.values():
        is_ui_flag, conf, _ = is_ui_text(state.original, state.fixed_translation)
        state.is_ui = is_ui_flag
        state.ui_confidence = conf


def _run_ui_length_checks(states: dict[RowId, RowState], lang: str):
    for state in states.values():
        assessment = assess_ui_length(
            row_id=state.row_id,
            original=state.original,
            translation=state.fixed_translation,
            is_ui=state.is_ui,
            lang=lang,
        )
        if assessment:
            state.short_text_length_policy = assessment.policy
            state.short_text_source_len = assessment.source_length
            state.short_text_target_len = assessment.target_length
            state.short_text_budget = assessment.budget
        for issue in check_ui_length(
            row_id=state.row_id,
            original=state.original,
            translation=state.fixed_translation,
            is_ui=state.is_ui,
            lang=lang,
        ):
            state.issues.append(issue)
            state.needs_human_review = True
            state.human_review_reason = issue.message
            state.ai_suggestion = state.fixed_translation
            state.review_confidence = issue.confidence


def _run_readability_checks(states: dict[RowId, RowState], lang: str):
    for state in states.values():
        for issue in check_readability(
            row_id=state.row_id,
            original=state.original,
            translation=state.fixed_translation,
            lang=lang,
        ):
            state.issues.append(issue)
            state.needs_human_review = True
            state.human_review_reason = issue.message
            state.ai_suggestion = state.fixed_translation
            state.review_confidence = issue.confidence


def rerun_quality_review(
    states: dict[RowId, RowState],
    *,
    term_lookup: dict | None,
    lang: str,
) -> tuple[dict[RowId, RowState], list]:
    """Re-run machine QA after AI merge so reports reflect final translations."""

    refreshed: dict[RowId, RowState] = {}
    for row_id, state in states.items():
        new_state = RowState(row_id, state.original, state.fixed_translation)
        new_state.fixed_translation = state.fixed_translation
        new_state.notes = list(state.notes)
        refreshed[row_id] = new_state

    _run_surface_fixes(refreshed, auto_fix=True, lang=lang)
    _run_variable_checks(refreshed, auto_fix=False)
    _run_term_checks(refreshed, term_lookup or {}, auto_fix=False, lang=lang)
    groups = _run_pattern_checks(refreshed, auto_fix=False)
    _run_chinese_residue_checks(refreshed, lang=lang)
    _run_ui_detection(refreshed)
    _run_ui_length_checks(refreshed, lang)
    _run_readability_checks(refreshed, lang)
    return refreshed, groups


def prepare_ai_review(
    states: dict[RowId, RowState],
    batch_size: int = 200,
    term_lookup: dict | None = None,
    lang: str = 'en',
    scope: str = 'all',
    include_term_priority: bool = False,
):
    """Prepare AI review batches from current states (after machine review).

    scope:
      - 'all': all rows
      - 'issues_only': only rows with any issue
      - 'term_hit': only rows whose original hits any term in term_lookup
    """
    _LOW_VALUE_ONLY = {'newline_mismatch'}
    _LOW_CONFIDENCE_THRESHOLD = 0.5

    def _is_low_value(s):
        """Skip rows that only have low-value issues AI can't fix well."""
        if not s.issues:
            return True
        issue_types = {getattr(i, 'check_type', '') for i in s.issues}
        if issue_types <= _LOW_VALUE_ONLY:
            return True
        if issue_types == {'pattern_inconsistency'}:
            max_conf = max((getattr(i, 'confidence', 1.0) for i in s.issues), default=1.0)
            if max_conf < _LOW_CONFIDENCE_THRESHOLD:
                return True
        return False

    if scope == 'issues_only':
        selected_states = [s for s in states.values() if s.issues and not _is_low_value(s)]
    elif scope == 'term_hit':
        if term_lookup:
            selected_states = [
                s for s in states.values()
                if any(cn in str(s.original) for cn in term_lookup if len(cn) >= 2)
            ]
        else:
            selected_states = list(states.values())
    else:
        selected_states = list(states.values())

    rows = []
    for s in selected_states:
        item = {
            'id': s.row_id,
            'original': s.original,
            'translation': s.fixed_translation,
        }
        if include_term_priority:
            item['is_ui'] = s.is_ui
            item['term_status'] = (
                'TERM_ERROR' if any(
                    getattr(i, 'check_type', '') in {'term_missing', 'term_partial_hit', 'term_capitalization', 'romanized_name_residue'}
                    for i in s.issues
                ) else 'TERM_OK'
            )
            item['term_issue_types'] = '; '.join(sorted(set(
                getattr(i, 'check_type', '')
                for i in s.issues
                if getattr(i, 'check_type', '') in {'term_missing', 'term_partial_hit', 'term_capitalization', 'romanized_name_residue'}
            )))
        if s.short_text_length_policy and s.short_text_length_policy != 'exempt':
            item['ui_length_policy'] = s.short_text_length_policy
            item['ui_length_source_len'] = int(s.short_text_source_len)
            item['ui_length_target_len'] = int(s.short_text_target_len)
            item['ui_length_budget'] = int(s.short_text_budget)
        rows.append(item)
    return prepare_all_batches(rows, batch_size=batch_size, term_lookup=term_lookup, lang=lang)
