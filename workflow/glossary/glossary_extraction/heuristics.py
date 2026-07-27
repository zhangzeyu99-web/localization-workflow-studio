"""Term extraction heuristics: text cleaning, scoring, and filtering."""

from __future__ import annotations

import html
import json
import re
from collections import Counter, defaultdict
from typing import Any

from glossary_extraction.constants import (
    ACTION_TERMS,
    BRACKET_TAG_RE,
    CAMEL_SPLIT_RE,
    CATEGORY_LABELS,
    CJK_RE,
    EN_COMPARE_RE,
    EN_WORD_RE,
    EFFECT_COMBO_TERM_RE,
    HIGH_CONFUSION_TERMS,
    HTML_TAG_RE,
    LEVEL_BATCH_ITEM_TERM_RE,
    NON_TERM_RE,
    NUMBERED_TITLE_RE,
    OBJECT_TERMS,
    PLACEHOLDER_RE,
    RARITY_TERMS,
    RESOURCE_TERMS,
    SENTENCE_PUNCT_RE,
    SPACE_RE,
    STAT_TERMS,
    STATUS_TERMS,
    SYSTEM_TERMS,
)
from glossary_extraction.models import Record
from glossary_extraction.name_policy import (
    PROPER_NAME_TYPES,
    assess_name_translation,
    classify_term_type,
    find_name_collisions,
    normalized_name,
)


def clean_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = html.unescape(text)
    text = HTML_TAG_RE.sub(" ", text)
    text = BRACKET_TAG_RE.sub("", text)
    text = PLACEHOLDER_RE.sub("", text)
    text = SPACE_RE.sub(" ", text).strip()
    return text


def normalize_english_for_compare(text: str) -> str:
    text = clean_text(text)
    text = CAMEL_SPLIT_RE.sub(" ", text)
    text = text.lower()
    text = re.sub(r"\s*\+\s*", "+", text)
    text = re.sub(r"[-_/]+", " ", text)
    text = EN_COMPARE_RE.sub(" ", text)
    text = SPACE_RE.sub(" ", text).strip()

    normalized_tokens: list[str] = []
    for token in text.split():
        if token.endswith("ies") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith(("oes", "ses", "xes", "zes", "ches", "shes")) and len(token) > 4:
            token = token[:-2]
        elif token.endswith("s") and len(token) > 3 and not token.endswith(("ss", "us", "is")):
            token = token[:-1]
        normalized_tokens.append(token)
    return " ".join(normalized_tokens)


def is_same_or_extended_usage(example_en: str, actual_en: str) -> bool:
    example_norm = normalize_english_for_compare(example_en)
    actual_norm = normalize_english_for_compare(actual_en)
    if not actual_norm or not example_norm:
        return False
    if actual_norm == example_norm:
        return True
    return f" {example_norm} " in f" {actual_norm} "


def split_usage_buckets(example_en: str, actual_counter: Counter[str]) -> tuple[Counter[str], Counter[str]]:
    example_counter: Counter[str] = Counter()
    manual_counter: Counter[str] = Counter()
    for actual_en, count in actual_counter.items():
        if is_same_or_extended_usage(example_en=example_en, actual_en=actual_en):
            example_counter[actual_en] += count
        else:
            manual_counter[actual_en] += count
    return example_counter, manual_counter


def collect_translation_diff(example_en: str, actual_counter: Counter[str]) -> dict[str, object]:
    same_counter, diff_counter = split_usage_buckets(
        example_en=example_en,
        actual_counter=actual_counter,
    )
    return {
        "has_diff": "Yes" if diff_counter else "No",
        "same_or_format_only_count": sum(same_counter.values()),
        "diff_count": sum(diff_counter.values()),
        "diff_variants": join_counter(diff_counter, limit=8),
        "diff_type": "manual_adaptation" if diff_counter else "",
    }


def token_roots(text: str) -> list[str]:
    roots: list[str] = []
    for token in EN_WORD_RE.findall(normalize_english_for_compare(text)):
        root = token
        if root.endswith("ing") and len(root) > 5:
            root = root[:-3]
        elif root.endswith("ed") and len(root) > 4:
            root = root[:-2]
        elif root.endswith("er") and len(root) > 4:
            root = root[:-2]
        elif root.endswith("ation") and len(root) > 7:
            root = root[:-5] + "e"
        roots.append(root)
    return roots


def titleize_word(word: str) -> str:
    if word.isupper():
        return word
    if word in {"hp", "atk", "def", "dmg", "cp"}:
        return word.upper()
    return word.capitalize()


def choose_en2_value(
    example_en: str,
    exact_diff_counter: Counter[str],
    manual_counter: Counter[str],
) -> str:
    if exact_diff_counter:
        return " | ".join(text for text, _ in exact_diff_counter.most_common(3))
    if not manual_counter:
        return ""

    manual_variants = manual_counter.most_common()
    top_text, top_count = manual_variants[0]
    second_count = manual_variants[1][1] if len(manual_variants) > 1 else 0
    total = sum(manual_counter.values())
    if top_count >= 2 and top_count > second_count and top_count / total >= 0.45:
        top_norm = normalize_english_for_compare(top_text)
        if top_norm and all(
            normalize_english_for_compare(text) == top_norm
            or is_same_or_extended_usage(example_en=top_text, actual_en=text)
            or is_same_or_extended_usage(example_en=text, actual_en=top_text)
            for text, _count in manual_variants[1:]
        ):
            return top_text

    example_roots = set(token_roots(example_en))
    root_counter: Counter[str] = Counter()

    for text, count in manual_counter.items():
        for root in token_roots(text):
            if root in example_roots or root in {"the", "a", "an", "of", "to", "for", "in", "on", "with", "and"}:
                continue
            root_counter[root] += count

    if not root_counter:
        return ""

    top_root, top_count = root_counter.most_common(1)[0]
    second_count = root_counter.most_common(2)[1][1] if len(root_counter) > 1 else 0
    if top_count < 2 or top_count <= second_count:
        return ""
    if top_count / total < 0.45:
        return ""
    return titleize_word(top_root)


def is_short_usage_candidate(record: Record, term: str, example_en: str) -> bool:
    if not record.target:
        return False
    if record.source == term:
        return True
    source_limit = max(8, len(term) + 4)
    target_limit = max(28, len(example_en) + 12) if example_en else 28
    return len(record.source) <= source_limit and len(record.target) <= target_limit


def is_valid_term(term: str) -> bool:
    if len(term) < 2 or len(term) > 12:
        return False
    if EFFECT_COMBO_TERM_RE.match(term):
        return False
    if LEVEL_BATCH_ITEM_TERM_RE.match(term):
        return False
    if SENTENCE_PUNCT_RE.search(term):
        return False
    if NON_TERM_RE.match(term):
        return False
    if not CJK_RE.search(term):
        return False
    if term.startswith(("+", "-", "/", "%")) or term.endswith(("+", "-", "/", "%")):
        return False
    return True


def strip_numbered_title_prefix(value: object) -> str:
    return clean_text(NUMBERED_TITLE_RE.sub("", "" if value is None else str(value)).strip())


def parse_json_like_value(value: object) -> Any | None:
    text = "" if value is None else str(value).strip()
    if not text.startswith("["):
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def first_string_from_json_like(value: object) -> str:
    parsed = parse_json_like_value(value)
    if isinstance(parsed, list) and parsed and isinstance(parsed[0], str):
        return strip_numbered_title_prefix(parsed[0])
    return clean_text(value)


def extract_structured_term_pairs(raw_source: object, raw_target: object) -> list[tuple[str, str]]:
    parsed_source = parse_json_like_value(raw_source)
    parsed_target = parse_json_like_value(raw_target)
    if not isinstance(parsed_source, list):
        return [(clean_text(raw_source), clean_text(raw_target))]

    pairs: list[tuple[str, str]] = []
    if parsed_source and isinstance(parsed_source[0], str):
        term = strip_numbered_title_prefix(parsed_source[0])
        target = first_string_from_json_like(raw_target)
        if is_valid_term(term):
            pairs.append((term, target))

    for index, source_item in enumerate(parsed_source):
        if not (isinstance(source_item, list) and source_item and isinstance(source_item[0], str)):
            continue
        term = strip_numbered_title_prefix(source_item[0])
        target = ""
        if isinstance(parsed_target, list) and index < len(parsed_target):
            target_item = parsed_target[index]
            if isinstance(target_item, list) and target_item and isinstance(target_item[0], str):
                target = strip_numbered_title_prefix(target_item[0])
        if is_valid_term(term):
            pairs.append((term, target))

    return pairs or [(clean_text(raw_source), clean_text(raw_target))]


def category_for(term: str) -> str:
    if term in RARITY_TERMS or any(key in term for key in ("品质", "稀有度")):
        return "rarity"
    if term in RESOURCE_TERMS:
        return "resource"
    if term in STAT_TERMS or any(key in term for key in ("伤害", "攻击", "生命", "防御", "暴击")):
        return "stat"
    if term in ACTION_TERMS:
        return "action"
    if "活动" in term:
        return "activity"
    if any(key in term for key in ("邮件", "信件")):
        return "mail"
    if any(key in term for key in ("公会", "联盟")):
        return "alliance"
    if any(key in term for key in ("副本", "秘境")):
        return "dungeon"
    if any(key in term for key in ("英雄", "角色", "职业")):
        return "hero"
    if any(key in term for key in ("怪物", "首领", "BOSS", "Boss", "boss")):
        return "monster"
    if "宠物" in term:
        return "pet"
    if any(key in term for key in ("武器", "装备", "护甲")):
        return "equipment"
    if any(key in term for key in ("道具", "宝箱", "药水")):
        return "item"
    if "技能" in term:
        return "skill"
    if any(key in term for key in ("纹章", "铭文", "宝石")):
        return "emblem"
    if term in SYSTEM_TERMS:
        return "ui"
    if term in OBJECT_TERMS:
        return "item"
    if term in STATUS_TERMS:
        return "ui"
    return "needs_review"


def join_counter(counter: Counter[str], limit: int = 5) -> str:
    if not counter:
        return ""
    return " | ".join(f"{text} ({count})" for text, count in counter.most_common(limit))


def risk_for(term: str, variants: int, hits: int, suggested_en: str) -> str:
    if variants > 1 or term in HIGH_CONFUSION_TERMS or not suggested_en:
        return "high"
    if hits >= 30:
        return "medium"
    return "low"


def priority_for(risk: str, hits: int) -> str:
    if risk == "high" or hits >= 80:
        return "P1"
    if hits >= 30:
        return "P2"
    return "P3"


def note_for(
    term: str,
    variants: int,
    exact_hits: int,
    hits: int,
    suggested_en: str,
    has_actual_diff: bool,
) -> str:
    notes: list[str] = []
    if variants > 1:
        notes.append("multiple English variants detected")
    if term in ACTION_TERMS:
        notes.append("action term needs consistency review")
    if term in RARITY_TERMS:
        notes.append("rarity ladder should stay globally aligned")
    if exact_hits == 1 and hits >= 20:
        notes.append("mostly embedded usage, review with context")
    if not suggested_en:
        notes.append("no stable English match found")
    if has_actual_diff:
        notes.append("actual short usages contain manual adaptation")
    return "; ".join(notes)


def counter_to_dict(counter: Counter[str]) -> dict[str, int]:
    return {key: int(value) for key, value in sorted(counter.items()) if key}


def dict_to_counter(value: dict[str, Any] | None) -> Counter[str]:
    counter: Counter[str] = Counter()
    if not value:
        return counter
    for key, raw in value.items():
        try:
            count = int(raw)
        except (TypeError, ValueError):
            continue
        if key and count > 0:
            counter[key] = count
    return counter


def merge_counters(*counters: Counter[str]) -> Counter[str]:
    merged: Counter[str] = Counter()
    for counter in counters:
        merged.update(counter)
    return merged


# Imported as a whole module (not from-imports) so the circular dependency with
# glossary_extraction.experience stays resolvable in any import order:
# experience.py imports helper functions defined above, while build_term_rows
# below only uses the experience-layer helpers at call time.
from glossary_extraction import experience


def build_term_rows(
    records: list[Record],
    min_hit: int,
    glossary_hit_threshold: int,
    curated_rules: dict[str, Any] | None = None,
    observations_store: dict[str, Any] | None = None,
    input_digest: str = "",
    include_empty_final_terms: bool = False,
    target_language: str = "EN",
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    curated_rules = curated_rules if curated_rules is not None else experience.new_curated_rules()
    observations_store = observations_store if observations_store is not None else experience.new_observation_store()
    label_counter: Counter[str] = Counter()
    label_translations: dict[str, Counter[str]] = defaultdict(Counter)
    exact_record_indexes: dict[str, list[int]] = defaultdict(list)

    for index, record in enumerate(records):
        if is_valid_term(record.source):
            label_counter[record.source] += 1
            exact_record_indexes[record.source].append(index)
            if record.target:
                label_translations[record.source][record.target] += 1

    rows_by_term: list[dict[str, object]] = []
    for term in sorted(set(label_counter)):
        hits = 0
        example_record: Record | None = None
        near_translations: Counter[str] = Counter()
        for record in records:
            if term not in record.source:
                continue
            hits += 1
            if example_record is None or len(record.source) < len(example_record.source):
                example_record = record
            if record.target and len(record.source) <= max(18, len(term) + 6):
                near_translations[record.target] += 1

        curated_state = experience.get_curated_term_state(curated_rules, term, create=False)
        type_decision = classify_term_type(
            term=term,
            exact_record_indexes=exact_record_indexes[term],
            records=records,
            curated_state=curated_state,
        )
        if hits < min_hit and not type_decision.bypass_frequency and not type_decision.needs_review:
            continue

        current_exact_translations = label_translations.get(term, Counter()).copy()
        primary_en, translation_source, translation_conflicts = experience.choose_primary_translation(
            current_counter=current_exact_translations,
            curated_state=curated_state,
        )
        suggested_en = primary_en or (
            near_translations.most_common(1)[0][0] if near_translations else ""
        )
        example_en = primary_en or (
            example_record.target if example_record and example_record.target else suggested_en
        )

        actual_short_counter: Counter[str] = Counter()
        diff_sample: Record | None = None
        for record in records:
            if term not in record.source:
                continue
            if not is_short_usage_candidate(record=record, term=term, example_en=example_en):
                continue
            actual_short_counter[record.target] += 1
            if record.target and not is_same_or_extended_usage(example_en=example_en, actual_en=record.target):
                if diff_sample is None or (len(record.source), len(record.target)) < (len(diff_sample.source), len(diff_sample.target)):
                    diff_sample = record

        example_usage_counter, manual_adaptation_counter = split_usage_buckets(
            example_en=example_en,
            actual_counter=actual_short_counter,
        )
        exact_diff_counter = Counter(
            {
                text: count
                for text, count in current_exact_translations.items()
                if not is_same_or_extended_usage(example_en=example_en, actual_en=text)
            }
        )
        en2_value = choose_en2_value(
            example_en=example_en,
            exact_diff_counter=exact_diff_counter,
            manual_counter=manual_adaptation_counter,
        )

        current_example_usage_counter = example_usage_counter.copy()
        current_manual_adaptation_counter = manual_adaptation_counter.copy()
        observation_state = experience.get_observation_term_state(observations_store, term)
        exact_translations, example_usage_counter, manual_adaptation_counter = experience.apply_observation_history(
            observation_state=observation_state,
            exact_translation_counter=current_exact_translations,
            example_usage_counter=example_usage_counter,
            manual_adaptation_counter=manual_adaptation_counter,
        )
        suggested_en, example_en, en2_value, exact_translations, example_usage_counter, manual_adaptation_counter = experience.apply_curated_preferences(
            curated_state=curated_state,
            term=term,
            suggested_en=suggested_en,
            example_en=example_en,
            en2_value=en2_value,
            exact_translation_counter=exact_translations,
            example_usage_counter=example_usage_counter,
            manual_adaptation_counter=manual_adaptation_counter,
        )
        if not suggested_en and exact_translations:
            suggested_en = exact_translations.most_common(1)[0][0]
        if not example_en:
            example_en = suggested_en
        if not suggested_en:
            suggested_en = example_en

        experience.update_observation_store(
            observation_state,
            input_digest=input_digest,
            exact_translation_counter=current_exact_translations,
            example_usage_counter=current_example_usage_counter,
            manual_adaptation_counter=current_manual_adaptation_counter,
        )

        diff_info = collect_translation_diff(example_en=example_en, actual_counter=actual_short_counter)
        risk = risk_for(term, len(exact_translations or near_translations), hits, suggested_en)
        category_override = clean_text(curated_state.get("category_override"))
        category_code = category_for(term)
        category = (
            type_decision.category
            or CATEGORY_LABELS.get(category_override, category_override)
            or CATEGORY_LABELS[category_code]
        )
        needs_review = type_decision.needs_review or category == "待确认"
        if needs_review:
            risk = "high"
        note = note_for(
            term=term,
            variants=len(exact_translations or near_translations),
            exact_hits=label_counter[term],
            hits=hits,
            suggested_en=suggested_en,
            has_actual_diff=diff_info["has_diff"] == "Yes",
        )
        if clean_text(curated_state.get("note")):
            note = f"{note}; {clean_text(curated_state.get('note'))}" if note else clean_text(curated_state.get("note"))
        name_policy = assess_name_translation(
            term_type=type_decision.term_type,
            translation=example_en,
            language=target_language,
        )

        row = {
            "ID": example_record.row_id if example_record else "",
            "CN": term,
            "EN": example_en,
            "EN2": en2_value,
            "SuggestedEN": suggested_en,
            "TranslationSource": translation_source,
            "TranslationConflict": "Yes" if translation_conflicts else "No",
            "TranslationConflictValues": " | ".join(translation_conflicts),
            "ExactCandidates": join_counter(exact_translations or near_translations),
            "ExampleUsages": join_counter(example_usage_counter, limit=8),
            "ManualAdaptations": join_counter(manual_adaptation_counter, limit=8),
            "ActualShortUsages": join_counter(actual_short_counter, limit=8),
            "HasActualDiff": diff_info["has_diff"],
            "DiffType": diff_info["diff_type"],
            "DiffVariants": diff_info["diff_variants"],
            "SameOrFormatOnlyCount": diff_info["same_or_format_only_count"],
            "DiffCount": diff_info["diff_count"],
            "Category": category,
            "TermType": type_decision.term_type,
            "TypeConfidence": type_decision.confidence,
            "TypeEvidence": " | ".join(type_decision.evidence),
            "NeedsReview": "Yes" if needs_review else "No",
            "NameWordCount": name_policy.word_count,
            "NameCoreWordCount": name_policy.core_word_count,
            "NameCharCount": name_policy.char_count,
            "NamePolicyWarnings": " | ".join(name_policy.warnings),
            "NameCollision": "No",
            "NameCollisionWith": "",
            "Risk": risk,
            "Priority": priority_for(risk, hits),
            "HitRows": hits,
            "ExactRows": label_counter[term],
            "ExampleID": example_record.row_id if example_record else "",
            "ExampleSource": example_record.source if example_record else "",
            "ExampleEN": example_record.target if example_record else "",
            "DiffExampleID": diff_sample.row_id if diff_sample else "",
            "DiffExampleSource": diff_sample.source if diff_sample else "",
            "DiffExampleEN": diff_sample.target if diff_sample else "",
            "Note": note,
        }
        if not curated_state.get("ignore"):
            rows_by_term.append(row)

    collisions = find_name_collisions(rows_by_term, curated_rules)
    for row in rows_by_term:
        collision_cn_values = collisions.get(normalized_name(row.get("EN")), [])
        if len(collision_cn_values) <= 1:
            continue
        row["NameCollision"] = "Yes"
        row["NameCollisionWith"] = " | ".join(collision_cn_values)
        row["Risk"] = "high"
        row["Priority"] = priority_for("high", int(row["HitRows"]))

    rows_by_term.sort(
        key=lambda row: (
            {"P1": 0, "P2": 1, "P3": 2}[row["Priority"]],
            {"high": 0, "medium": 1, "low": 2}[row["Risk"]],
            -int(row["HitRows"]),
            row["CN"],
        )
    )

    glossary_rows = [
        row
        for row in rows_by_term
        if row["NeedsReview"] != "Yes"
        and row["NameCollision"] != "Yes"
        and (
            int(row["HitRows"]) >= glossary_hit_threshold
            or row["Risk"] == "high"
            or row["TermType"] in PROPER_NAME_TYPES
        )
    ]
    high_risk_rows = [
        row for row in rows_by_term if row["Risk"] == "high" or row["NeedsReview"] == "Yes"
    ]
    manual_rows = [row for row in rows_by_term if row["HasActualDiff"] == "Yes"]
    final_rows = list(glossary_rows) if include_empty_final_terms else [
        row for row in glossary_rows if row["EN"] or row["EN2"]
    ]
    return rows_by_term, glossary_rows, high_risk_rows, manual_rows, final_rows
