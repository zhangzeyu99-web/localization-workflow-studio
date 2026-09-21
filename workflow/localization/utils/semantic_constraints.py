"""High-confidence, source-bound semantic constraints for CN -> EN/ES/PT.

Findings block acceptance and require correction or contextual review. They do
not claim to establish semantic equivalence for unrestricted natural language.
"""
import re
from utils.quantity_guard import visible_text

ENTITY_WORDS = {
    '编队': {'en': r'formation|squad', 'es': r'formación|escuadrón', 'pt': r'formação|esquadrão'},
    '队伍': {'en': r'team|squad', 'es': r'equipo|escuadrón', 'pt': r'equipe|esquadrão'},
    'VIP': {'en': 'VIP', 'es': 'VIP', 'pt': 'VIP'},
}
ROMAN = ('', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X')
CONDITION_VERBS = {
    'en': {'attack': r'\b(?:attacking|attack|attacks|assaulting|assault)\b', 'defend': r'\b(?:defending|defend|defends|defense|defence)\b'},
    'es': {'attack': r'\b(?:atacar|ataca|atacan|atacando|ataque)\b', 'defend': r'\b(?:defender|defiende|defienden|defendiendo|defensa|defensiv[oa]s?)\b'},
    'pt': {'attack': r'\b(?:atacar|ataca|atacam|atacando|ataque)\b', 'defend': r'\b(?:defender|defende|defendem|defendendo|defesa)\b'},
}
ENEMY = {'en': r'\b(?:enem(?:y|ies)|opponent|opposing|hostile)\b', 'es': r'\b(?:enemig[oa]s?|oponentes?|rival(?:es)?)\b', 'pt': r'\b(?:inimig[oa]s?|oponentes?|adversári[oa]s?|riva(?:l|is))\b'}
NEGATION = {'en': r"\b(?:not|no|never|cannot|can't|unable|unavailable|impossible|without|disabled|banned|prohibited|muted)\b|n't\b", 'es': r'\b(?:no|sin|nunca|imposible|inhabilitad[oa]|prohibid[oa]|silenciad[oa])\b', 'pt': r'\b(?:não|nao|sem|nunca|impossível|indisponível|desativad[oa]|proibid[oa]|silenciad[oa])\b'}


def semantic_constraint_issues(source: str, target: str, lang: str) -> list[tuple[str, str]]:
    lang = lang.lower().replace('_', '-').split('-')[0]
    if lang not in CONDITION_VERBS:
        return []
    src, dst = visible_text(source), visible_text(target)
    if not dst.strip():
        return []  # Empty targets have their own structural blocker.
    issues = []
    for entity, words in ENTITY_WORDS.items():
        for match in re.finditer(re.escape(entity) + r'\s*(\d+)', src, re.I):
            number = int(match[1])
            forms = [str(number)] + ([ROMAN[number]] if 0 < number < len(ROMAN) else [])
            n = '(?:' + '|'.join(forms) + ')'
            label = '(?:' + words[lang] + ')'
            if not re.search(rf'\b{label}\s*(?:n[o.º°]*\s*)?{n}(?!\d|[A-Za-z])|(?<!\w){n}(?:st|nd|rd|th|\.?[ªº])?\s+{label}\b', dst, re.I):
                issues.append(('semantic_entity_number_missing', f'Numbered entity not preserved: {entity}{number}'))
    # Inspect action predicates, not the attack/defence stat names elsewhere.
    attack_matches = list(re.finditer(r'(?:攻击|进攻)(?!命中)[^，。；\n]{0,20}时', src))
    attack = any(not re.search(r'(?:受到|被)[^，。；\n]{0,8}$', src[:m.start()]) for m in attack_matches)
    defend = bool(re.search(r'(?:防守|防御)[^，。；\n]{0,20}时', src))
    if attack != defend:
        expected = 'attack' if attack else 'defend'
        # Nominal stat words do not satisfy a condition; require a conditional
        # clause or an explicit action form such as "when attacking" / "al atacar".
        condition = {'en': r'\b(?:when|while|during|on)\s+(.+)', 'es': r'\b(?:al|cuando|mientras|durante)\s+(.+)', 'pt': r'\b(?:ao|quando|enquanto|durante)\s+(.+)'}[lang]
        clause = re.search(condition, dst, re.I)
        body = clause[1] if clause else dst
        if not re.search(CONDITION_VERBS[lang][expected], body, re.I):
            issues.append(('semantic_action_condition_missing', f'Expected {expected} action condition needs review'))
        if attack and re.search(r'(?:攻击|进攻)敌方', src) and not re.search(ENEMY[lang], body, re.I):
            issues.append(('semantic_enemy_scope_missing', 'Enemy ownership in attack condition is missing'))
    # Narrow explicit prohibitions. Negation elsewhere in a long sentence cannot
    # prove this proposition, so long/multi-clause content stays with deep review.
    equivalent_only = {'en': r'\bonly\s+(?:identical|matching)', 'es': r'\bsolo\b.*\bidéntic', 'pt': r'\b(?:só|somente)\b.*\bidêntic'}
    restriction_equivalent = '不是相同' in src and re.search(equivalent_only[lang], dst, re.I)
    if len(src) <= 55 and not restriction_equivalent and not re.search(r'[，,；;。\n]', src) and re.search(r'无法|不能|^不可|禁止', src):
        if not re.search(NEGATION[lang], dst, re.I):
            issues.append(('semantic_negation_missing', 'Explicit prohibition/negation needs review'))
    return list(dict.fromkeys(issues))
