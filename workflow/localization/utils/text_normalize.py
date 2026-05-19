"""Shared text normalization for all QA modules.

All modules must use these functions instead of ad-hoc regex,
ensuring consistent handling of escapes, placeholders, tags, and punctuation.
"""
import re

_BACKSLASH_ESCAPE = re.compile(r'\\([_!#=\[\]{}()\\*+\-.<>|~])')

VAR_PATTERN = re.compile(r'\{[^}]+\}')
SQUARE_PLACEHOLDER_PATTERN = re.compile(r'\[(?!/?color\b)(?:[A-Za-z]+\d+|\d+)\]')
BOXED_INDEX_PATTERN = re.compile(r'⟦(\d+)⟧')
PLAIN_INDEX_PATTERN = re.compile(r'\[(\d+)\]')
BBCODE_OPEN = re.compile(r'(?:\[color\s*=[^\]]*\]|<color\s*=[^>]*>)', re.IGNORECASE)
BBCODE_CLOSE = re.compile(r'(?:\[/color\]|</color>)', re.IGNORECASE)
BBCODE_ANY = re.compile(r'(?:\[/?color[^\]]*\]|</?color(?:=[^>]+)?>)', re.IGNORECASE)
GENERIC_BBCODE_TAG_PATTERN = re.compile(r'\[/?[A-Za-z]+(?:=[^\]]+)?\]')
NEWLINE_TAG = re.compile(r'\\n')
STRIP_TAGS = re.compile(r'\[/?color[^\]]*\]|</?color(?:=[^>]+)?>|\{[^}]+\}|\[(?!/?color\b)(?:[A-Za-z]+\d+|\d+)\]|\[/?[A-Za-z]+(?:=[^\]]+)?\]')
_CORE_SOURCE_TOKEN_PATTERN = re.compile(r'\{[^}]+\}|\[(?!/?color\b)(?:[A-Za-z]+\d+|\d+)\]|\[/?[A-Za-z]+(?:=[^\]]+)?\]|</?color(?:=[^>]+)?>|\\n|\n')
_TITLE_BRACKET_PATTERN = re.compile(r'[【】]')
_FULLWIDTH_PAREN_PATTERN = re.compile(r'[（）]')

_FULLWIDTH_TRANSLATION_MAP = str.maketrans({
    '【': '[',
    '】': ']',
    '（': '(',
    '）': ')',
    '：': ':',
    '，': ',',
    '；': ';',
    '！': '!',
    '？': '?',
    '％': '%',
    '＋': '+',
    '－': '-',
    '　': ' ',
})

_PROMOTED_STAT_SOURCE_PATTERN = re.compile(
    r'^(?P<size1>\[size=\d+\])(?P<text1>.*?)(?P<size1_close>\[/size\])'
    r'(?P<size2>\[size=\d+\])(?P<color_open>\[[A-Za-z]+\d+\])'
    r'(?P<text2>.*?)(?P<color_close>\[[A-Za-z]+\d+\])(?P<size2_close>\[/size\])$'
)
_PROMOTED_STAT_TRANSLATION_PATTERN = re.compile(
    r'^(?P<color_open>\[[A-Za-z]+\d+\])(?P<text1>.*?)(?P<color_close>\[[A-Za-z]+\d+\])'
    r'(?P<size2>\[size=\d+\])(?P<color_open2>\[[A-Za-z]+\d+\])\s*'
    r'(?P<text2>.*?)(?P<color_close2>\[[A-Za-z]+\d+\])(?P<size2_close>\[/size\])$'
)


def normalize_escapes(text: str) -> str:
    """Remove backslash escapes (e.g. \\_ -> _, \\! -> !) for consistent comparison."""
    return _BACKSLASH_ESCAPE.sub(r'\1', str(text))


def strip_tags_and_vars(text: str) -> str:
    """Remove BBCode tags and placeholder tokens."""
    t = STRIP_TAGS.sub('', normalize_escapes(str(text)))
    return re.sub(r'\s+', ' ', t).strip()


def extract_vars(text: str) -> list[str]:
    """Extract all protected placeholder tokens after normalizing escapes."""
    normalized = normalize_escapes(str(text))
    return VAR_PATTERN.findall(normalized) + SQUARE_PLACEHOLDER_PATTERN.findall(normalized)


def extract_bbcode_opens(text: str) -> list[str]:
    """Extract all [color=xxx] open tags after normalizing escapes."""
    return BBCODE_OPEN.findall(normalize_escapes(str(text)))


def extract_bbcode_closes(text: str) -> list[str]:
    """Extract all [/color] close tags after normalizing escapes."""
    return BBCODE_CLOSE.findall(normalize_escapes(str(text)))


def count_newlines(text: str) -> int:
    """Count \\n occurrences after normalizing escapes."""
    return len(NEWLINE_TAG.findall(normalize_escapes(str(text))))


def build_source_token_map(text: str) -> list[str]:
    """Build the token index map used by upstream placeholder-boxing outputs.

    Upstream content tends to number core placeholders/newlines first,
    then number fullwidth title brackets afterwards.
    """
    normalized = normalize_escapes(str(text))
    tokens = [m.group(0) for m in _CORE_SOURCE_TOKEN_PATTERN.finditer(normalized)]
    for match in _TITLE_BRACKET_PATTERN.finditer(normalized):
        tokens.append('[' if match.group(0) == '【' else ']')
    for match in _FULLWIDTH_PAREN_PATTERN.finditer(normalized):
        tokens.append('(' if match.group(0) == '（' else ')')
    return tokens


def normalize_english_punctuation(text: str) -> str:
    """Convert fullwidth punctuation to ASCII for English-like outputs."""
    normalized = str(text).translate(_FULLWIDTH_TRANSLATION_MAP).replace('、', ',')
    normalized = re.sub(r'([,;:])(?=\S)', r'\1 ', normalized)
    normalized = re.sub(r'([(\[])\s+', r'\1', normalized)
    normalized = re.sub(r'\s+([\])])', r'\1', normalized)
    normalized = re.sub(r' {2,}', ' ', normalized)
    return normalized.strip()


def repair_translation_surface(original: str, translation: str, lang: str = 'en') -> str:
    """Repair boxed/index placeholders and normalize English punctuation.

    The repair is intentionally conservative:
    - map boxed tokens like ⟦0⟧ back to source placeholders by source token index
    - map plain index placeholders like [0] back when a source token exists
    - normalize fullwidth punctuation to ASCII for English/Latin outputs
    """
    repaired = normalize_escapes(str(translation))
    source_tokens = build_source_token_map(original)

    def _replace_boxed(match: re.Match[str]) -> str:
        index = int(match.group(1))
        if 0 <= index < len(source_tokens):
            return source_tokens[index]
        return match.group(0)

    repaired = BOXED_INDEX_PATTERN.sub(_replace_boxed, repaired)

    def _replace_plain_index(match: re.Match[str]) -> str:
        index = int(match.group(1))
        if 0 <= index < len(source_tokens):
            candidate = source_tokens[index]
            if candidate != '\n':
                return candidate
        return match.group(0)

    repaired = PLAIN_INDEX_PATTERN.sub(_replace_plain_index, repaired)
    repaired = _repair_promoted_stat_layout(original, repaired)

    if lang in {'en', 'idn', 'fr', 'de', 'tr', 'es', 'pt', 'ru'}:
        repaired = normalize_english_punctuation(repaired)

    return repaired


def _repair_promoted_stat_layout(original: str, translation: str) -> str:
    """Repair a common broken layout where size tags are boxed out of order.

    Example:
      [c0]Greatly promoted [s0][size=30][c0] ATK and HP[s0][/size]
    becomes:
      [size=20]Greatly promoted[/size][size=30][c0]ATK and HP[s0][/size]
    """
    source_match = _PROMOTED_STAT_SOURCE_PATTERN.match(str(original))
    translation_match = _PROMOTED_STAT_TRANSLATION_PATTERN.match(str(translation))
    if not source_match or not translation_match:
        return translation

    if (
        translation_match.group('color_open') != source_match.group('color_open')
        or translation_match.group('color_close') != source_match.group('color_close')
        or translation_match.group('color_open2') != source_match.group('color_open')
        or translation_match.group('color_close2') != source_match.group('color_close')
    ):
        return translation

    text1 = translation_match.group('text1').strip()
    text2 = translation_match.group('text2').strip()
    if not text1 or not text2:
        return translation

    return (
        f"{source_match.group('size1')}{text1}{source_match.group('size1_close')}"
        f"{source_match.group('size2')}{source_match.group('color_open')}"
        f"{text2}{source_match.group('color_close')}{source_match.group('size2_close')}"
    )
