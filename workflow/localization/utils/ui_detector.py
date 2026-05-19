"""UI text detection module.

Identifies whether a text entry is a UI element (button, label, menu item, etc.)
versus narrative/dialog text. UI text should use shorter, more concise translations.

Supports auto-detection and manual override.
"""
import re

# Thresholds
MAX_UI_CHAR_LENGTH = 40
MAX_UI_WORD_COUNT = 8

# Patterns that indicate UI text
_UI_CHINESE_KEYWORDS = [
    '按钮', '标签', '菜单', '选项', '确认', '取消', '返回',
    '设置', '退出', '开始', '结束', '提交', '保存', '删除',
    '升级', '购买', '充值', '领取', '抽奖', '签到', '刷新',
    '查看', '详情', '关闭', '打开', '前往', '点击',
]

_UI_ENGLISH_PATTERNS = [
    r'^(OK|Cancel|Confirm|Back|Close|Open|Save|Delete|Submit|Exit|Start|Stop)$',
    r'^(Yes|No|Accept|Decline|Skip|Retry|Continue|Next|Previous|Done)$',
    r'^(Buy|Purchase|Upgrade|Unlock|Collect|Claim|Redeem|Refresh|View)$',
    r'^Lv\.\s*\d+',
    r'^\d+[%x×]',
]
_UI_COMPILED = [re.compile(p, re.IGNORECASE) for p in _UI_ENGLISH_PATTERNS]

# Patterns that indicate non-UI (narrative/dialog) text
_NARRATIVE_INDICATORS = [
    r'[.!?。！？]$',      # ends with sentence punctuation
    r',.*,',              # multiple commas (complex sentence)
    r'\b(I|you|we|they|he|she)\b',  # personal pronouns
    r"['\u2019](s|t|re|ve|ll|d)\b",  # contractions
]
_NARRATIVE_COMPILED = [re.compile(p, re.IGNORECASE) for p in _NARRATIVE_INDICATORS]


def is_ui_text_auto(
    original: str,
    translation: str,
) -> tuple[bool, float]:
    """Auto-detect if a text pair is UI text.

    Returns:
        (is_ui, confidence) where confidence is 0.0-1.0
    """
    original = str(original)
    translation = str(translation)
    score = 0.0

    # Length-based signals
    trans_len = len(translation.strip())
    trans_words = len(translation.strip().split())

    if trans_len <= 15:
        score += 0.4
    elif trans_len <= MAX_UI_CHAR_LENGTH:
        score += 0.2
    else:
        score -= 0.3

    if trans_words <= 3:
        score += 0.3
    elif trans_words <= MAX_UI_WORD_COUNT:
        score += 0.1
    else:
        score -= 0.2

    # Chinese keyword signals
    for kw in _UI_CHINESE_KEYWORDS:
        if kw in original:
            score += 0.2
            break

    # English pattern signals
    for pattern in _UI_COMPILED:
        if pattern.search(translation.strip()):
            score += 0.3
            break

    # No verb structure (likely label)
    if not re.search(r'\b(is|are|was|were|have|has|had|will|can|do|does|did)\b',
                     translation, re.IGNORECASE):
        if trans_words <= 4:
            score += 0.1

    # Narrative counter-signals
    narrative_hits = 0
    for pattern in _NARRATIVE_COMPILED:
        if pattern.search(translation):
            narrative_hits += 1
    if narrative_hits > 0:
        score -= 0.2 * narrative_hits

    # Clamp to [0, 1]
    confidence = max(0.0, min(1.0, score))
    is_ui = confidence >= 0.4

    return is_ui, round(confidence, 2)


def is_ui_text(
    original: str,
    translation: str,
    manual_override: bool | None = None,
) -> tuple[bool, float, str]:
    """Determine if a text pair is UI text.

    Args:
        original: Chinese source text
        translation: English translation
        manual_override: If set, overrides auto-detection. True=UI, False=non-UI, None=auto.

    Returns:
        (is_ui, confidence, mode) where mode is 'auto' or 'manual'
    """
    if manual_override is not None:
        return manual_override, 1.0, 'manual'

    is_ui_result, confidence = is_ui_text_auto(original, translation)
    return is_ui_result, confidence, 'auto'
