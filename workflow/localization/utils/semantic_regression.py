"""Narrow source-conditioned regressions, not a general semantic quality score."""
import re


def known_semantic_regressions(row: dict, lang: str, target: str) -> list[str]:
    if lang.upper() != "FR" or row.get("source_mode") != "en":
        return []
    source = str(row.get("translation_source") or row.get("reference_en") or "")
    # 不将普通的头痛/头部健康句子，或正确的 fatigue ... avec ça 习语误拦。
    source_idiom = re.search(r"\bworry your (?:pretty )?(?:little )?head about (?:it|this|that)\b", source, re.I)
    wrong_object = re.search(r"\bsoucis?\s+pour\s+(?:ta|votre)\s+(?:jolie\s+)?(?:petite\s+)?t[êe]te\b", target, re.I)
    return ["fr_worry_idiom_object_drift"] if source_idiom and wrong_object else []
