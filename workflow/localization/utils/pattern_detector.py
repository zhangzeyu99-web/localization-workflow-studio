"""Sentence pattern consistency detector.

Core algorithm:
1. Create Chinese structural fingerprints by preserving anchors (prefix/suffix)
   while normalizing variable-length middle segments (proper nouns, item names).
2. Group rows by fingerprint.
3. Within each group, identify English slot fillers (proper nouns that vary)
   and create English structural templates.
4. Select the best translation pattern per group.
5. Flag and optionally fix inconsistencies.
"""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

VAR_PATTERN = re.compile(r'\{[^}]+\}')
SQUARE_PLACEHOLDER_PATTERN = re.compile(r'\[(?!/?color\b)(?:[A-Za-z]+\d+|\d+)\]')
BOXED_INDEX_PATTERN = re.compile(r'⟦\d+⟧')
BBCODE_PATTERN = re.compile(r'\[/?color[^\]]*\]', re.IGNORECASE)
NUMBER_PATTERN = re.compile(r'\d+')
CN_CHAR_PATTERN = re.compile(r'[\u4e00-\u9fa5]+')
PUNCTUATION_SPLIT = re.compile(r'([，。！？、：；\u201c\u201d\u2018\u2019()\s,.:;!?()]+)')


@dataclass
class PatternGroup:
    template: str
    row_ids: list[int] = field(default_factory=list)
    originals: list[str] = field(default_factory=list)
    translations: list[str] = field(default_factory=list)
    en_templates: list[str] = field(default_factory=list)
    best_pattern: str = ''
    best_translation_example: str = ''
    inconsistent_ids: list[int] = field(default_factory=list)


@dataclass
class PatternCheckResult:
    row_id: int
    check_type: str
    severity: str
    message: str
    original: str = ''
    translation: str = ''
    auto_fix: str = ''
    confidence: float = 1.0
    group_template: str = ''
    best_pattern: str = ''


def _bucket(length: int) -> str:
    if length <= 6:
        return 'S'
    if length <= 15:
        return 'M'
    return 'L'


def create_chinese_template(text: str) -> str:
    """Create a structural fingerprint from Chinese text.

    Preserves punctuation and short segments verbatim. For longer segments,
    keeps a 2-char prefix and 2-char suffix as anchors and replaces the
    variable middle (proper nouns, item names) with a length bucket.
    """
    t = str(text)
    t = VAR_PATTERN.sub('{V}', t)
    t = SQUARE_PLACEHOLDER_PATTERN.sub('{V}', t)
    t = BOXED_INDEX_PATTERN.sub('{V}', t)
    t = BBCODE_PATTERN.sub('', t)
    t = NUMBER_PATTERN.sub('{N}', t)

    segments = PUNCTUATION_SPLIT.split(t)
    result_parts: list[str] = []

    for seg in segments:
        if PUNCTUATION_SPLIT.fullmatch(seg):
            result_parts.append(seg)
            continue

        cn_chars = CN_CHAR_PATTERN.findall(seg)
        total_cn = sum(len(c) for c in cn_chars)

        if total_cn <= 4 or len(seg) <= 6:
            result_parts.append(seg)
        else:
            prefix = seg[:2]
            suffix = seg[-2:]
            mid_len = len(seg) - 4
            result_parts.append(f"{prefix}*{_bucket(mid_len)}*{suffix}")

    template = ''.join(result_parts).strip()
    template = re.sub(r'\s+', ' ', template)
    return template


def _find_slot_words(translations: list[str]) -> set[str]:
    """Find words that vary across translations (likely proper nouns / slot fillers).

    Only considers capitalized words that appear in some but not all translations.
    """
    if len(translations) < 2:
        return set()

    def tokenize(text: str) -> list[str]:
        clean = BBCODE_PATTERN.sub('', text)
        clean = VAR_PATTERN.sub('', clean)
        clean = SQUARE_PLACEHOLDER_PATTERN.sub('', clean)
        clean = BOXED_INDEX_PATTERN.sub('', clean)
        return re.findall(r"[A-Za-z'\u2019]+", clean)

    word_sets = [set(tokenize(t)) for t in translations]
    all_words: Counter = Counter()
    for ws in word_sets:
        for w in ws:
            all_words[w] += 1

    n = len(translations)
    slots = set()
    for word, count in all_words.items():
        # Present in some but not all; likely a proper noun slot filler
        if 0 < count < n and len(word) > 2 and word[0].isupper():
            slots.add(word)

    # Supplement with pairwise diff for short groups
    if len(translations) <= 10:
        word_lists = [tokenize(t) for t in translations]
        for i in range(min(3, len(word_lists))):
            for j in range(i + 1, min(4, len(word_lists))):
                sm = SequenceMatcher(None, word_lists[i], word_lists[j])
                for tag, i1, i2, j1, j2 in sm.get_opcodes():
                    if tag in ('replace', 'insert', 'delete'):
                        for w in word_lists[i][i1:i2]:
                            if len(w) > 2 and w[0].isupper():
                                slots.add(w)
                        for w in word_lists[j][j1:j2]:
                            if len(w) > 2 and w[0].isupper():
                                slots.add(w)

    return slots


def create_english_template(text: str, slot_words: set[str] | None = None) -> str:
    """Create a structural template from English text.

    Only replaces known slot words (proper nouns that vary across the group).
    Keeps all structural words intact for accurate comparison.
    """
    t = str(text)
    t = VAR_PATTERN.sub('{V}', t)
    t = SQUARE_PLACEHOLDER_PATTERN.sub('{V}', t)
    t = BOXED_INDEX_PATTERN.sub('{V}', t)
    t = BBCODE_PATTERN.sub('', t)
    t = NUMBER_PATTERN.sub('{N}', t)

    if slot_words:
        for word in sorted(slot_words, key=len, reverse=True):
            t = re.sub(r'\b' + re.escape(word) + r'\b', '{S}', t)

    t = re.sub(r'\s+', ' ', t).strip()
    return t


def _select_best_pattern(
    en_templates: list[str],
    translations: list[str],
) -> tuple[str, str, float]:
    """Select the best English template for a group.

    Uses frequency as the primary heuristic, adjusted by quality signals.
    """
    if not en_templates:
        return '', '', 0.0

    counter = Counter(en_templates)
    best_template, top_count = counter.most_common(1)[0]
    total = len(en_templates)
    ratio = top_count / total

    if ratio >= 0.8:
        confidence = 0.95
    elif ratio >= 0.6:
        confidence = 0.80
    elif ratio >= 0.4:
        confidence = 0.60
    else:
        # No clear majority — flag for human review
        confidence = 0.40

    best_example = ''
    for tmpl, trans in zip(en_templates, translations):
        if tmpl == best_template:
            best_example = trans
            break

    return best_template, best_example, confidence


def _build_fix_from_pattern(
    target_translation: str,
    best_example: str,
    slot_words: set[str],
) -> str:
    """Reconstruct a fixed translation by mapping the best pattern onto this row's slot fillers.

    Returns empty string when a safe substitution cannot be determined.
    """
    target_clean = BBCODE_PATTERN.sub('', VAR_PATTERN.sub('', target_translation))
    target_clean = SQUARE_PLACEHOLDER_PATTERN.sub('', target_clean)
    target_clean = BOXED_INDEX_PATTERN.sub('', target_clean).strip()
    example_clean = BBCODE_PATTERN.sub('', VAR_PATTERN.sub('', best_example))
    example_clean = SQUARE_PLACEHOLDER_PATTERN.sub('', example_clean)
    example_clean = BOXED_INDEX_PATTERN.sub('', example_clean).strip()

    target_words = re.findall(r"[A-Za-z'\u2019]+", target_clean)
    example_words = re.findall(r"[A-Za-z'\u2019]+", example_clean)

    # Only consider capitalized words that are truly unique to one side
    target_word_set = set(w.lower() for w in target_words)
    example_word_set = set(w.lower() for w in example_words)

    target_unique = []
    seen = set()
    for w in target_words:
        if w.lower() not in seen and w[0].isupper() and w.lower() not in example_word_set:
            target_unique.append(w)
            seen.add(w.lower())

    example_unique = []
    seen = set()
    for w in example_words:
        if w.lower() not in seen and w[0].isupper() and w.lower() not in target_word_set:
            example_unique.append(w)
            seen.add(w.lower())

    if not target_unique or not example_unique:
        return ''
    if len(target_unique) != len(example_unique):
        return ''

    result = best_example
    for ex_w, tgt_w in zip(example_unique, target_unique):
        result = re.sub(r'\b' + re.escape(ex_w) + r'\b', tgt_w, result)

    # Validate: no doubled words introduced
    result_words = result.lower().split()
    for i in range(len(result_words) - 1):
        if result_words[i] == result_words[i + 1] and len(result_words[i]) > 2:
            return ''

    # Preserve original BBCode tags
    orig_tags = BBCODE_PATTERN.findall(target_translation)
    if orig_tags and not BBCODE_PATTERN.search(result):
        return ''

    return result if result != best_example else ''


def detect_patterns(
    rows: list[dict],
    min_group_size: int = 3,
) -> tuple[list[PatternGroup], list[PatternCheckResult]]:
    """Detect sentence pattern groups and check consistency.

    Args:
        rows: List of dicts with keys: id, original, translation.
        min_group_size: Minimum group size to analyse (default 3).

    Returns:
        (groups, issues)
    """
    # Step 1: group by Chinese template
    template_groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        tmpl = create_chinese_template(row['original'])
        template_groups[tmpl].append(row)

    groups: list[PatternGroup] = []
    issues: list[PatternCheckResult] = []

    for tmpl, group_rows in template_groups.items():
        if len(group_rows) < min_group_size:
            continue

        group = PatternGroup(template=tmpl)
        for r in group_rows:
            group.row_ids.append(r['id'])
            group.originals.append(r['original'])
            group.translations.append(r['translation'])

        # Step 2: detect slot words and build English templates
        slot_words = _find_slot_words(group.translations)
        group.en_templates = [
            create_english_template(t, slot_words) for t in group.translations
        ]

        # Step 3: select best pattern
        best_tmpl, best_example, confidence = _select_best_pattern(
            group.en_templates, group.translations,
        )
        group.best_pattern = best_tmpl
        group.best_translation_example = best_example

        # Step 4: flag inconsistencies
        for i, (en_tmpl, row_data) in enumerate(zip(group.en_templates, group_rows)):
            if en_tmpl != best_tmpl:
                group.inconsistent_ids.append(row_data['id'])

                auto_fix = _build_fix_from_pattern(
                    row_data['translation'], best_example, slot_words,
                )

                severity = 'error' if confidence >= 0.7 else 'warning'

                issues.append(PatternCheckResult(
                    row_id=row_data['id'],
                    check_type='pattern_inconsistency',
                    severity=severity,
                    message=(
                        f"Pattern mismatch: '{en_tmpl}' vs group standard '{best_tmpl}'"
                    ),
                    original=row_data['original'],
                    translation=row_data['translation'],
                    auto_fix=auto_fix,
                    confidence=confidence,
                    group_template=tmpl,
                    best_pattern=best_tmpl,
                ))

        groups.append(group)

    return groups, issues
