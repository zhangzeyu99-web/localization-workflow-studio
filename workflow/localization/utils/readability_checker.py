"""Readability checks for over-compressed localization output.

This module blocks two common failure modes in game localization:
- opaque internal-code style abbreviations, for example "PERR", "DTT", "IDNE"
- clipped words produced by aggressive UI shortening, for example "rewa", "obta"
- title-case overuse in error/status messages, for example "Too Many Roles"
"""
from __future__ import annotations

import re

from utils.variable_checker import CheckResult

_RUNTIME_PLACEHOLDER = re.compile(
    r'<[^>]+>|\{[^}]+\}|\[[A-Za-z]+\d+\]|%[dfs]|##\d+',
    re.IGNORECASE,
)
_ALL_CAPS_TOKEN = re.compile(r'^[A-Z]{2,8}$')
_OPAQUE_CODE_WITH_PLACEHOLDER = re.compile(
    r'^(?:##\d+)*[A-Z]{2,8}(?:##\d+|[A-Z0-9])*$'
)

ALLOWED_GAME_ABBREVIATIONS = {
    "AI",
    "AOE",
    "API",
    "ATK",
    "BP",
    "CD",
    "CN",
    "CP",
    "DEF",
    "DMG",
    "DPS",
    "EN",
    "EXP",
    "FPS",
    "GM",
    "BOSS",
    "HD",
    "HP",
    "ID",
    "MAX",
    "MT",
    "NPC",
    "OK",
    "PVE",
    "PVP",
    "RNG",
    "SFX",
    "SR",
    "SSR",
    "SS",
    "UI",
    "URL",
    "VIP",
    "II",
    "III",
    "IV",
    "V",
    "VI",
    "VII",
    "VIII",
    "IX",
}

_CLIPPED_WORD_PATTERN = re.compile(
    r'\b(?:'
    r'acct|acti|adde|afte|alre|anon|appo|arri|assa|assi|atta|avai|basi|batt|beig|blac|blee|bles|bloc|bubb|cale|'
    r'cann|capa|caus|chal|chap|char|clas|clea|coll|comm|cond|conf|coun|cur|dama|del|deta|diam|dist|devi|'
    r'doct|docto|driv|dura|effe|elec|ener|ente|equi|esse|expe|expi|figh|foll|foun|frie|grou|hist|hosp|'
    r'imme|impr|inco|inef|init|intr|defe|engi|gath|incr|lege|leve|loca|logi|memb|meth|mgmt|modi|norm|obta|'
    r'offl|opti|orde|othe|outp|outs|perm|perms|phon|phoe|piec|plac|plea|posi|poti|prod|prof|prog|purc|rada|rand|'
    r'rapi|reac|reas|rece|reco|recy|redu|refr|regi|rema|repa|repl|req|resc|rese|resi|reso|resu|rewa|rwd|rwds|'
    r'scie|sear|seas|sele|sett|smel|spen|stag|ston|stor|stro|stru|supp|surv|swip|symb|toda|tomo|tmrw|'
    r'toke|trai|trac|tran|trea|troo|unde|uned|unli|unre|unsu|unti|unwo|upgr|yday'
    r')\b',
    re.IGNORECASE,
)
_ROMANIZED_NAME_RESIDUE_PATTERN = re.compile(r'\b(?:yifang)\b', re.IGNORECASE)
_SOURCE_SENSITIVE_CLIPPED_PATTERNS = [
    (
        re.compile(r'\u5bfc\u6f14'),
        re.compile(r'(?<![A-Za-z])(?:Dir\.?|Dire|Dais)(?![A-Za-z])', re.IGNORECASE),
    ),
    (
        re.compile(r'\u533b\u751f'),
        re.compile(r'\bDoct(?:o)?\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u80fd\u6e90\u5b66\u5bb6'),
        re.compile(r'\b(?:Ener|Scie)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u7ed3\u6784\u4e13\u5bb6'),
        re.compile(r'\b(?:Stru|Expe)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u51b6\u70bc\u4e13\u5bb6'),
        re.compile(r'\b(?:Smel|Expe)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u6539\u826f\u7cbe\u7cb9'),
        re.compile(r'\b(?:Pts|impr|esse)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u79ef\u5206|\u70b9\u6570|\d+\u70b9'),
        re.compile(r'\bPts\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u6682\u65e0\u641c\u7d22\u7ed3\u679c'),
        re.compile(r'\b(?:sear|resu)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u751f\u4ea7|\u4ea7\u51fa|\u63d0\u5347'),
        re.compile(r'\b(?:incr|impr|outp|prod|ston)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u653b\u51fb'),
        re.compile(r'\b(?:atta|miss|relo|surp|outp)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u9632\u5fa1'),
        re.compile(r'\b(?:abso|defe|rein|outp)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u751f\u547d'),
        re.compile(r'\b(?:assa|rein|outp)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u53ec\u96c6'),
        re.compile(r'\b(?:gath|lege|outs)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u82f1\u96c4\u7ecf\u9a8c|\u6302\u673a\u7ecf\u9a8c'),
        re.compile(r'\b(?:expe|outp)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u7535\u80fd'),
        re.compile(r'\b(?:elec|ener)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u88c5\u7532|\u673a\u7ffc|\u5f15\u64ce|\u96f7\u8fbe|\u793c\u5305'),
        re.compile(r'\b(?:armo|avai|crac|engi|garr|shad|shen|supe|tian|thun)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u96f7\u9706'),
        re.compile(r'\b(?:orde|thun)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u8352\u6f20\u5546\u961f'),
        re.compile(r'\b(?:dese|cara)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u5b9e\u529b'),
        re.compile(r'\b(?:stre)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u6700\u7ec8'),
        re.compile(r'\b(?:fina)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u8ffd\u8e2a|\u6218\u672f'),
        re.compile(r'\b(?:tact\.?|trac|bull)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u7206\u88c2|\u71c3\u7206'),
        re.compile(r'\b(?:expl|thro)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u7a7f\u900f|\u8d2f\u5c04'),
        re.compile(r'\b(?:pene|bull)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u8986\u76d6|\u7cbe\u51c6|\u9b45\u5f71'),
        re.compile(r'\b(?:satu|stri|prec|phan)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u591a\u91cd\u5236\u88c1'),
        re.compile(r'\b(?:mult|sanc)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u667a\u80fd\u5236\u5bfc'),
        re.compile(r'\b(?:inte|guid)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u8f90\u88c2\u5c04\u51fb'),
        re.compile(r'\b(?:radi)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u65e0\u754f\u8a93\u76df'),
        re.compile(r'\b(?:pled)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u8363\u8000\u5951\u7ea6'),
        re.compile(r'\b(?:glor|cont)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u4e0d\u548c\u8c10\u8bcd\u6c47|\u654f\u611f\u8bcd\u6c47|\u5185\u5bb9|\u8d21\u732e'),
        re.compile(r'\b(?:cont|disc|sens|cann|empt)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u56de\u590d|\u6d88\u606f|\u64a4\u56de|\u8fc7\u671f|\u90ae\u4ef6|\u672a\u8bfb|\u9a9a\u6270|\u5237\u5c4f|\u5783\u573e\u4fe1\u606f|\u4fe1\u606f'),
        re.compile(r'\b(?:hara|mess)\b', re.IGNORECASE),
    ),
    (
        re.compile(r'\u968f\u673a\u5c45\u6c11|\u8d44\u6e90'),
        re.compile(r'(?<![A-Za-z])Res\.(?![A-Za-z])', re.IGNORECASE),
    ),
]
_WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z']*")
_STATUS_OR_ERROR_SOURCE = re.compile(
    r'失败|错误|异常|超时|过多|不足|无法|不能|不可|尚未|暂无|'
    r'未达到|未找到|未开启|未购买|未完成|未解锁|未拥有|未加入|未激活|'
    r'已结束|已过期|已被|已经|已达|已领取|已发送|已加入|已拒绝|已完成|已满|已售罄|'
    r'校验|验证|重连|成功|参数|警告|提示|网络|条件|上限|封禁|被封'
)
_PRESERVE_CASE_WORDS = {
    "Android",
    "App",
    "Discord",
    "Facebook",
    "Google",
    "ID",
    "iOS",
    "PvE",
    "PvP",
    "Twitter",
    "UI",
    "VIP",
    "YouTube",
}


def _visible_text(text: str) -> str:
    visible = _RUNTIME_PLACEHOLDER.sub('', str(text or ''))
    return re.sub(r'\s+', ' ', visible).strip()


def _has_opaque_code(text: str) -> bool:
    raw = str(text or '').strip()
    visible = _visible_text(raw)
    if not visible:
        return False
    if _ALL_CAPS_TOKEN.match(visible):
        return visible.upper() not in ALLOWED_GAME_ABBREVIATIONS
    if _OPAQUE_CODE_WITH_PLACEHOLDER.match(raw):
        stripped = re.sub(r'##\d+', '', raw)
        return bool(stripped) and stripped.upper() not in ALLOWED_GAME_ABBREVIATIONS
    return False


def _is_title_word(word: str) -> bool:
    if word.upper() in ALLOWED_GAME_ABBREVIATIONS:
        return False
    if word in _PRESERVE_CASE_WORDS:
        return False
    return len(word) > 1 and word[0].isupper() and word[1:].islower()


def _is_title_case_overuse(original: str, translation: str) -> bool:
    if not _STATUS_OR_ERROR_SOURCE.search(str(original or '')):
        return False

    text = _visible_text(translation)
    words = _WORD_PATTERN.findall(text)
    if len(words) < 2:
        return False

    title_words = [w for w in words if _is_title_word(w)]
    lower_words = [
        w for w in words
        if w.islower() and w.lower() not in {'a', 'an', 'and', 'as', 'at', 'by', 'for', 'in', 'of', 'on', 'or', 'the', 'to'}
    ]
    return len(title_words) >= 2 and not lower_words


def _sentence_case(text: str) -> str:
    words = _WORD_PATTERN.findall(text)
    if not words:
        return text

    first_word_seen = False

    def replace(match: re.Match) -> str:
        nonlocal first_word_seen
        word = match.group(0)
        if word.upper() in ALLOWED_GAME_ABBREVIATIONS or word in _PRESERVE_CASE_WORDS:
            return word
        lowered = word.lower()
        if not first_word_seen:
            first_word_seen = True
            return lowered[:1].upper() + lowered[1:]
        return lowered

    return _WORD_PATTERN.sub(replace, text)


def _find_source_sensitive_clipped_word(original: str, translation: str) -> str:
    visible = _visible_text(translation)
    for source_pattern, target_pattern in _SOURCE_SENSITIVE_CLIPPED_PATTERNS:
        if not source_pattern.search(str(original or '')):
            continue
        match = target_pattern.search(visible)
        if match:
            return match.group(0)
    return ''


def check_readability(row_id: int, original: str, translation: str, lang: str = 'en') -> list[CheckResult]:
    """Return hard readability issues caused by over-compression.

    The check is conservative: it allows established game abbreviations such as
    HP, ATK, DEF, DMG, PVP, and VIP, but flags opaque internal codes and clipped
    English fragments that are not user-facing text.
    """
    if lang not in {'en', 'idn', 'th', 'vi', 'fr', 'de', 'tr', 'es', 'pt', 'ru'}:
        return []

    results: list[CheckResult] = []
    text = str(translation or '')

    if _has_opaque_code(text):
        results.append(CheckResult(
            row_id=row_id,
            check_type='opaque_abbreviation',
            severity='error',
            message='Opaque or internal-code abbreviation found in translation',
            original=original,
            translation=translation,
            confidence=0.95,
        ))

    romanized_name = _ROMANIZED_NAME_RESIDUE_PATTERN.search(_visible_text(text))
    if romanized_name:
        results.append(CheckResult(
            row_id=row_id,
            check_type='romanized_name_residue',
            severity='error',
            message=f"Romanized Chinese-name residue found in translation: {romanized_name.group(0)}",
            original=original,
            translation=translation,
            confidence=0.95,
        ))

    clipped = _CLIPPED_WORD_PATTERN.search(_visible_text(text))
    source_sensitive_clipped = _find_source_sensitive_clipped_word(original, text)
    clipped_token = clipped.group(0) if clipped else source_sensitive_clipped
    if clipped_token:
        results.append(CheckResult(
            row_id=row_id,
            check_type='clipped_word',
            severity='error',
            message=f"Clipped word found in translation: {clipped_token}",
            original=original,
            translation=translation,
            confidence=0.9,
        ))

    if lang == 'en' and _is_title_case_overuse(original, text):
        results.append(CheckResult(
            row_id=row_id,
            check_type='title_case_overuse',
            severity='warning',
            message='Title Case overused in status/error style translation',
            original=original,
            translation=translation,
            auto_fix=_sentence_case(text),
            confidence=0.8,
        ))

    return results
