"""Checks explicit CN durations/counts independently of legacy small-number waivers.

EN/ES/PT only. These are deterministic review blockers, not a semantic pass.
Tags cannot supply numbers; a target count cannot satisfy an attack count.
"""
from __future__ import annotations

import re
from decimal import Decimal

WORDS = {
    'en': {'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
           'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10, 'a': 1, 'an': 1},
    'es': {'cero': 0, 'uno': 1, 'una': 1, 'un': 1, 'dos': 2, 'tres': 3,
           'cuatro': 4, 'cinco': 5, 'seis': 6, 'siete': 7, 'ocho': 8, 'nueve': 9, 'diez': 10},
    'pt': {'zero': 0, 'um': 1, 'uma': 1, 'dois': 2, 'duas': 2, 'três': 3,
           'tres': 3, 'quatro': 4, 'cinco': 5, 'seis': 6, 'sete': 7, 'oito': 8,
           'nove': 9, 'dez': 10},
}
DURATION_UNITS = {
    'en': {'hour': r'h(?:ours?|rs?)?', 'minute': r'm(?:in(?:ute)?s?)?', 'second': r's(?:ec(?:ond)?s?)?', 'day': r'd(?:ays?)?'},
    'es': {'hour': r'h(?:oras?|rs?)?', 'minute': r'min(?:utos?)?', 'second': r's(?:eg(?:undos?)?)?', 'day': r'd(?:ías?)?'},
    'pt': {'hour': r'h(?:oras?|rs?)?', 'minute': r'min(?:utos?)?', 'second': r's(?:eg(?:undos?)?)?', 'day': r'd(?:ias?)?'},
}
COUNTS = {'en': r'times?|hits?|strikes?|attacks?', 'es': r'veces|vez|golpes?|ataques?', 'pt': r'vezes|vez|golpes?|ataques?'}
EACH = {'en': r'\b(?:each|every|per)\b', 'es': r'\bcada\b', 'pt': r'\bcada\b'}
PER_HIT = {
    'en': r'\b(?:each|every)\b.{0,30}\b(?:deal|deals|dealing|hit|attack|strike|time)|\b(?:per|with each)\s+(?:hit|attack|strike)',
    'es': r'\bcada\s+(?:golpe|ataque|vez|uno|una)|\bpor\s+(?:golpe|ataque)',
    'pt': r'\bcada\s+(?:golpe|ataque|vez|um|uma)|\bpor\s+(?:golpe|ataque)',
}
SOURCE_UNITS = {'小时': 'hour', '分钟': 'minute', '秒钟': 'second', '秒': 'second', '天': 'day', '次': 'count'}
SOURCE_RE = re.compile(r'(?<![\d.])(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>小时|分钟|秒钟|秒|天|次)')


def visible_text(text: str) -> str:
    return re.sub(r'<[^>]*>|\[[^\]]*\]|\{[^{}]*\}|#[A-Za-z]\d*#|##\d+', ' ', str(text or ''))


def _language(lang: str) -> str:
    return lang.lower().replace('_', '-').split('-')[0]


def _amounts(text: str, units: str, lang: str) -> set[Decimal]:
    words = '|'.join(sorted(WORDS[lang], key=len, reverse=True))
    number = rf'(?:\d+(?:[.,]\d+)?|{words})'
    # A following digit permits compact duration strings (1h30min).
    pattern = rf'(?<![\w.,])({number})\s*[-–]?\s*(?:{units})(?![^\W\d_])'
    values = set()
    for match in re.finditer(pattern, text, re.I):
        token = match[1].lower()
        values.add(Decimal(WORDS[lang][token]) if token in WORDS[lang] else Decimal(token.replace(',', '.')))
    return values


def quantity_issues(source: str, target: str, lang: str) -> list[tuple[str, str]]:
    lang = _language(lang)
    if lang not in WORDS:
        return []
    src, dst = visible_text(source), visible_text(target)
    issues = []
    for match in SOURCE_RE.finditer(src):
        amount = Decimal(match['number'])
        role = SOURCE_UNITS[match['unit']]
        if role == 'count':
            available = _amounts(dst, COUNTS[lang], lang)
            if lang == 'en':
                if re.search(r'\bonce\b', dst, re.I): available.add(Decimal(1))
                if re.search(r'\btwice\b', dst, re.I): available.add(Decimal(2))
            # 每完成1次 -> for each completion / por cada... is equivalent.
            if amount == 1 and re.search(r'每[^，。；\n]{0,16}$', src[:match.start()]) and re.search(EACH[lang], dst, re.I):
                continue
            # Ordinary noncombat counts may naturally precede the action noun.
            combat = bool(re.search(r'攻击|普攻|命中|击打', src[:match.start()]))
            if re.search(r'次数[^，。；\n]{0,12}$', src[:match.start()]):
                # The number of attempts is adjusted to 3: unit precedes value.
                reverse = {'en': r'(?:attempts?|times?)', 'es': r'(?:intentos?|veces)', 'pt': r'(?:tentativas?|vezes)'}[lang]
                if re.search(reverse + r'[^.;\n]{0,100}(?<!\d)' + re.escape(str(amount)) + r'(?!\d)', dst, re.I):
                    continue
            if not combat:
                if amount in _amounts(dst, r'[^\W\d_]+', lang):
                    continue
            if amount not in available:
                issues.append(('quantity_count_missing', f'Unmatched explicit count: {match[0]}'))
        else:
            units = DURATION_UNITS[lang][role]
            available = _amounts(dst, units, lang)
            if amount == 1 and re.search(r'每隔?\s*$', src[:match.start()]):
                every = {'en': r'(?:every|each)', 'es': 'cada', 'pt': 'cada'}[lang]
                if re.search(rf'\b{every}\s+(?:{units})\b', dst, re.I):
                    available.add(Decimal(1))
            if role == 'day':
                # Server Day 28 / days 1-4 are ordinal labels, not durations.
                for day in re.finditer(rf'\b(?:{units})\s+(\d+)(?:\s*[-–]\s*(\d+))?', dst, re.I):
                    available.update(Decimal(x) for x in day.groups() if x)
            if amount not in available:
                issues.append(('quantity_duration_mismatch', f'Unmatched duration value/unit: {match[0]} ({role})'))
    if re.search(r'每次(?:攻击)?造成', src) and not re.search(PER_HIT[lang], dst, re.I):
        issues.append(('quantity_per_hit_missing', 'Source specifies damage per hit; explicit target scope needs review'))
    return list(dict.fromkeys(issues))
