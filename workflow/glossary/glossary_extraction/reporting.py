"""Project brief, project signals, translation prompt, and markdown reporting."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from glossary_extraction.constants import CATEGORY_LABELS, PROJECT_SIGNAL_GROUPS
from glossary_extraction.heuristics import join_counter
from glossary_extraction.models import Record


def keyword_evidence(records: list[Record], keywords: set[str]) -> tuple[int, Counter[str]]:
    row_hits = 0
    keyword_counter: Counter[str] = Counter()
    for record in records:
        matched = False
        source_text = record.source.lower()
        for keyword in keywords:
            if keyword.lower() in source_text:
                keyword_counter[keyword] += 1
                matched = True
        if matched:
            row_hits += 1
    return row_hits, keyword_counter


def infer_project_signals(records: list[Record], limit: int = 5) -> list[dict[str, object]]:
    signals: list[dict[str, object]] = []
    for label, keywords in PROJECT_SIGNAL_GROUPS.items():
        row_hits, evidence_counter = keyword_evidence(records, keywords)
        if not row_hits:
            continue
        signals.append(
            {
                "label": label,
                "hit_rows": row_hits,
                "evidence": join_counter(evidence_counter, limit=6),
            }
        )
    signals.sort(key=lambda item: (-int(item["hit_rows"]), str(item["label"])))
    return signals[:limit]


def markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _header in headers) + " |",
    ]
    for row in rows:
        escaped = [str(value).replace("|", "\\|") for value in row]
        lines.append("| " + " | ".join(escaped) + " |")
    return "\n".join(lines)


def source_samples(records: list[Record], signals: list[dict[str, object]], limit: int = 5) -> list[str]:
    if not signals:
        return []
    signal_labels = {str(signal["label"]) for signal in signals}
    keywords: set[str] = set()
    for label, group_keywords in PROJECT_SIGNAL_GROUPS.items():
        if label in signal_labels:
            keywords.update(group_keywords)

    samples: list[str] = []
    seen: set[str] = set()
    for record in records:
        if len(record.source) > 48:
            continue
        if not any(keyword in record.source for keyword in keywords):
            continue
        sample = f"{record.row_id}: {record.source}" if record.row_id else record.source
        if sample in seen:
            continue
        samples.append(sample)
        seen.add(sample)
        if len(samples) >= limit:
            break
    return samples


def category_distribution(rows: list[dict[str, object]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        category = str(row.get("Category") or "other")
        counter[CATEGORY_LABELS.get(category, category)] += 1
    return counter


def top_terms(rows: list[dict[str, object]], limit: int = 8) -> list[str]:
    terms: list[str] = []
    for row in sorted(rows, key=lambda item: (-int(item.get("HitRows") or 0), str(item.get("CN") or "")))[:limit]:
        cn = str(row.get("CN") or "")
        en = str(row.get("EN") or "")
        en2 = str(row.get("EN2") or "")
        hit_rows = int(row.get("HitRows") or 0)
        english = en if not en2 else f"{en} / {en2}"
        terms.append(f"{cn} -> {english} ({hit_rows})" if english else f"{cn} ({hit_rows})")
    return terms


def style_guidance(signals: list[dict[str, object]], categories: Counter[str], target_coverage: int) -> list[str]:
    labels = {str(signal["label"]) for signal in signals}
    guidance = [
        "游戏内容/UI 部分尽量精简，适配移动端按钮、弹窗、任务和道具说明。",
        "剧情对话必须自然、地道、通顺，参考美剧日常对白节奏，避免逐字直译。",
        "变量、数字、换行、富文本标签和占位符必须原样保留。",
    ]
    if "合成/经营" in labels:
        guidance.append("合成、订单、生产、仓库等玩法术语保持统一，不在不同系统中来回换词。")
    if "花店/装修" in labels or "休闲/女性向" in labels:
        guidance.append("整体语气偏温暖、轻松、生活化，避免硬核、军工或过度严肃的表达。")
    if "战斗/RPG养成" in labels or categories.get("战斗属性/数值", 0):
        guidance.append("战斗、属性、技能说明优先准确表达机制，不使用夸张营销词替代数值含义。")
    if "基地/建筑经营" in labels:
        guidance.append("建筑、基地、升级线采用稳定系统名；同一建筑不要在 HQ/Base/Headquarters 之间漂移。")
    if "活动/商业化" in labels:
        guidance.append("活动、礼包、商店文案可以有吸引力，但必须短、明确、不过度夸张。")
    if "社交/公会竞争" in labels:
        guidance.append("公会、排行、竞技相关术语保持玩家社区常用表达，如 Guild、Ranking、Arena。")
    if "剧情/叙事" in labels:
        guidance.append("角色对话要保留人物关系、情绪冲突和轻喜剧节奏，可使用自然口语与缩写。")
    if target_coverage:
        guidance.append("已有英文译文视为项目历史用法；当它和术语表冲突时，优先检查是否属于手动适配 EN2。")
    return guidance


def project_type_from_signals(signals: list[dict[str, object]]) -> str:
    labels = {str(signal["label"]) for signal in signals}
    if "飞行/射击题材" in labels and "战斗/RPG养成" in labels:
        return "科幻战机 / 飞行射击 / RPG养成"
    if "飞行/射击题材" in labels:
        return "飞行射击"
    if "战斗/RPG养成" in labels and "社交/公会竞争" in labels and "基地/建筑经营" in labels:
        return "战斗/RPG养成 / 轻SLG"
    if {"合成/经营", "花店/装修", "剧情/叙事"} <= labels:
        return "合成经营 / 花店修复 / 轻剧情休闲"
    if {"合成/经营", "剧情/叙事"} <= labels:
        return "合成经营 / 轻剧情休闲"
    if "花店/装修" in labels:
        return "花店装修 / 休闲经营"
    if "休闲/女性向" in labels:
        return "女性向休闲"
    if "战斗/RPG养成" in labels:
        return "战斗/RPG养成"
    if "剧情/叙事" in labels:
        return "剧情向休闲"
    return "移动游戏"


def target_user_from_signals(signals: list[dict[str, object]]) -> str:
    labels = {str(signal["label"]) for signal in signals}
    if "飞行/射击题材" in labels:
        return "偏中重度、喜欢战机养成、战斗数值、装备强化和活动推进的移动端玩家。"
    if "战斗/RPG养成" in labels:
        return "偏中度、关注战力成长、英雄/装备养成、活动奖励和竞技排名的移动端玩家。"
    if "花店/装修" in labels or "休闲/女性向" in labels:
        return "偏休闲、喜欢合成/装修/经营和轻剧情的女性向或轻度玩家。"
    if "合成/经营" in labels:
        return "喜欢轻策略、收集、订单推进和长期经营成长的休闲玩家。"
    if "剧情/叙事" in labels:
        return "重视角色关系、剧情推进和自然对白体验的玩家。"
    return "移动端游戏玩家。"


def signal_hit_map(signals: list[dict[str, object]]) -> dict[str, int]:
    return {str(signal["label"]): int(signal["hit_rows"]) for signal in signals}


def content_focus_from_signals(signals: list[dict[str, object]]) -> str:
    labels = {str(signal["label"]) for signal in signals}
    hits = signal_hit_map(signals)
    focus: list[str] = []
    if "飞行/射击题材" in labels:
        focus.append("战机、导弹、射击、弹幕等战斗内容")
    if "战斗/RPG养成" in labels:
        focus.append("英雄、装备、技能、属性和战力成长")
    if "基地/建筑经营" in labels:
        focus.append("建造、升级、采集、生产等基地系统")
    if hits.get("合成/经营", 0) >= 20:
        focus.append("合成、订单、生产、仓库等玩法 UI")
    if hits.get("花店/装修", 0) >= 10:
        focus.append("花店修复、装饰和生活化物件")
    if "剧情/叙事" in labels:
        focus.append("角色剧情对话")
    if "活动/商业化" in labels:
        focus.append("活动、礼包和奖励")
    return "；".join(focus) if focus else "系统 UI、玩法说明和剧情文本"


def tone_rule_from_signals(signals: list[dict[str, object]]) -> str:
    labels = {str(signal["label"]) for signal in signals}
    if "飞行/射击题材" in labels:
        return "整体语气冷静、利落、偏科幻军事；战机、装备、导弹、技能和战斗数值要专业清晰，避免可爱化、生活化或过度口语化。"
    if "战斗/RPG养成" in labels:
        return "整体语气清晰、有力量感；战斗、英雄、装备和数值成长要准确直接，避免弱化机制或夸张营销。"
    if "花店/装修" in labels or "休闲/女性向" in labels:
        return "整体语气偏轻松、温暖、生活化；涉及花店、装修、订单、合成、经营时避免硬核或过度严肃的表达。"
    if "合成/经营" in labels:
        return "整体语气轻松、清晰、偏休闲；合成、订单、生产和仓库说明要短句化，避免复杂长句。"
    return "整体语气清晰、自然、符合移动游戏语境；不要为了润色改变玩法含义。"


def build_translation_prompt(
    project_name: str,
    signals: list[dict[str, object]],
    categories: Counter[str],
    key_terms: list[str],
    target_coverage: int,
) -> str:
    project_type = project_type_from_signals(signals)
    tone_rule = tone_rule_from_signals(signals)
    term_rule = "关键术语以随附术语表为准，EN 为标准译法，EN2 为项目中稳定出现的手动适配译法。"
    if not key_terms:
        term_rule = "如未提供术语表，需先从上下文判断固定系统名，保持同一中文术语的英文一致。"
    existing_en_rule = (
        "已有英文译文代表项目历史用法；如现有译法不自然，可以优化，但不要破坏已固定的系统术语。"
        if target_coverage
        else "当前输入可能没有英文列；先按项目类型和术语表建立统一英语风格。"
    )
    return "\n".join(
        [
            f"你是一位资深游戏本地化译者，正在翻译《{project_name}》这款{project_type}游戏。",
            "译文需符合以下要求：",
            "1. 游戏内容/UI/玩法说明尽量精简，适配移动游戏按钮、弹窗、任务、道具和奖励说明；",
            "2. 剧情对话必须自然、地道、通顺，参考美剧日常对白节奏，保留角色语气、冲突、幽默和情绪，不要逐字直译；",
            f"3. {tone_rule}",
            f"4. {term_rule}",
            f"5. {existing_en_rule}",
            "6. 保留所有游戏代码、变量、数字、换行、颜色标签、HTML/富文本标签和占位符，如 {0}、%s、<color> 等；",
            "7. 无法确认的专有名词或信息缺口用 [TBD] 标记，不要自行编造设定。",
        ]
    )


def build_project_brief(
    project_name: str,
    sheet_name: str,
    records: list[Record],
    all_rows: list[dict[str, object]],
    glossary_rows: list[dict[str, object]],
    manual_rows: list[dict[str, object]],
    material_sources: list[str] | None = None,
) -> tuple[str, str]:
    source_rows = len(records)
    target_coverage = sum(1 for record in records if record.target)
    signals = infer_project_signals(records, limit=10)
    categories = category_distribution(glossary_rows or all_rows)
    key_terms = top_terms(glossary_rows or all_rows)
    project_type = project_type_from_signals(signals)
    target_user = target_user_from_signals(signals)
    content_focus = content_focus_from_signals(signals)
    tone_rule = tone_rule_from_signals(signals)
    prompt = build_translation_prompt(
        project_name=project_name,
        signals=signals,
        categories=categories,
        key_terms=key_terms,
        target_coverage=target_coverage,
    )

    markdown = "\n".join(
        [
            f"# {project_name} 翻译提示词与项目元信息",
            "",
            "## 🤖 AI 生成的专属翻译提示词",
            "",
            "```",
            prompt,
            "```",
            "",
            "## 📌 项目元信息",
            "",
            markdown_table(
                ["项目", "信息"],
                [
                    ["游戏类型", project_type],
                    ["目标用户", target_user],
                    ["内容构成", content_focus],
                    ["翻译风格", f"UI/玩法精简适配移动端；剧情自然、地道、通顺，参考美剧日常对白；{tone_rule}"],
                    ["信息来源", "语言表" if not material_sources else "语言表；" + "；".join(material_sources[:6])],
                    ["语言资产", f"{source_rows} 条文本，已有英文 {target_coverage} 条。"],
                    ["生成日期", datetime.now().strftime("%Y-%m-%d")],
                ],
            ),
            "",
        ]
    )
    return markdown, prompt
