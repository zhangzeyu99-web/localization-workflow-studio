from __future__ import annotations

import json
import re
from typing import Any

from .. import db
from ..config import REAL_PROVIDERS, load_settings, normalize_provider_name
from ..languages import language_spec, require_supported_language
from ..translation_batches import cap_context_text as _cap_context_text
from .common import (
    TERM_REFERENCE_RULE,
    _language_assets_summary,
    _project_material_labels,
    read_project_harness,
    write_project_harness,
)
from .semantic_qa import _call_semantic_provider, _parse_semantic_qa_payload

def _is_warplane_project(project: dict[str, Any], intro: str, material_labels: list[str], asset_notes: list[str] | None = None) -> bool:
    text = " ".join(
        [
            str(project.get("name") or ""),
            str(project.get("type") or ""),
            str(project.get("description") or ""),
            intro,
            *material_labels,
            *(asset_notes or []),
        ]
    )
    return any(token in text for token in ("战机", "飞行射击", "导弹", "装备", "Warplane", "warplane"))


def _build_project_profile(project: dict[str, Any], intro: str, asset_notes: list[str], target_language: str = "en", material_packet: dict[str, Any] | None = None) -> dict[str, Any]:
    target_language = require_supported_language(target_language)
    spec = language_spec(target_language)
    material_labels = _project_material_labels(project["id"])
    description = project.get("description", "") or intro or "；".join(asset_notes[:3])
    is_warplane = _is_warplane_project(project, intro, material_labels, asset_notes)
    style_language = "英文" if target_language == "en" else spec.label
    if is_warplane:
        game_type = "科幻战机 / 飞行射击 / RPG养成"
        target_audience = "偏中重度、喜欢战机养成、战斗数值、装备强化和活动推进的移动端玩家。"
        content_scope = "战机、导弹、射击、弹幕等战斗内容；英雄、装备、技能、属性和战力成长；建造、升级、采集、生产等基地系统；角色剧情对话；活动、礼包和奖励。"
        translation_style = f"翻译为自然{style_language}；UI/玩法精简适配移动端；剧情自然、地道、通顺，保留角色语气；整体语气冷静、利落、偏科幻军事；战机、装备、导弹、技能和战斗数值要专业清晰，避免可爱化、生活化或过度口语化。"
        tone = "冷静、利落、偏科幻军事"
    else:
        game_type = project.get("type", "") or "游戏本地化项目"
        target_audience = "目标语区游戏玩家；以当前项目描述和参考素材为准。"
        content_scope = description or "UI、系统、任务、道具、活动和剧情文本。"
        translation_style = f"准确翻译为自然{style_language}；UI/按钮/任务短句清晰；剧情对话自然但不改设定；术语以项目术语表为准；保留变量、占位符、富文本标签、数字和换行。"
        tone = "自然、准确、游戏 UI 友好"
    seed = _display_profile_seed_from_packet(material_packet or {"materials": []})
    signal_seed = _language_table_signal_seed(material_packet or {"materials": []})
    seed = {**signal_seed, **{key: value for key, value in seed.items() if value}}
    return {
        "project_name": project["name"],
        "project_type": project.get("type", ""),
        "description": description,
        "intro": intro,
        "asset_notes": asset_notes,
        "source_materials": material_labels,
        "game_type": game_type,
        "target_audience": target_audience,
        "content_scope": content_scope,
        "translation_style": translation_style,
        "language_assets": seed.get("language_assets") or _language_assets_summary(project["id"]),
        "target_language": target_language,
        "target_language_label": spec.label,
        "target_language_name": spec.prompt_name,
        "tone": tone,
        "generated_date": db.now_iso()[:10],
        "analysis_source": "template",
        "analysis_warning": "未配置 API key，只生成本地规则草稿，未进行 AI 资料分析。",
        "display_game_type": seed.get("display_game_type") or game_type,
        "display_target_audience": seed.get("display_target_audience") or target_audience,
        "display_content_scope": seed.get("display_content_scope") or content_scope,
        "display_worldview": seed.get("display_worldview") or tone,
        "display_translation_style": seed.get("display_translation_style") or translation_style,
        "display_focus": seed.get("display_focus") or "",
        "display_key_terms": seed.get("display_key_terms") or "",
    }


def _display_profile_seed_from_packet(material_packet: dict[str, Any]) -> dict[str, str]:
    source_text = " ".join(str(material.get("excerpt") or "") for material in material_packet.get("materials", []) if isinstance(material, dict))

    def table_value(*labels: str) -> str:
        for label in labels:
            pattern = rf"\|\s*{re.escape(label)}(?:（[^|]*）)?\s*\|\s*([^|]+?)\s*\|"
            match = re.search(pattern, source_text)
            if match:
                return re.sub(r"\s+", " ", match.group(1)).strip()
        return ""

    return {
        "display_game_type": table_value("游戏类型"),
        "display_target_audience": table_value("目标用户"),
        "display_content_scope": table_value("内容构成", "内容范围"),
        "display_worldview": table_value("视觉与世界观", "世界观"),
        "display_translation_style": table_value("翻译风格", "风格要求"),
        "display_focus": table_value("重点注意", "注意事项"),
    }


def _clean_markdown_cell(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace("\\|", "|")
    text = re.sub(r"<br\s*/?>", "；", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _markdown_table_pairs(text: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for line in text.splitlines():
        raw = line.strip()
        if not raw.startswith("|") or not raw.endswith("|"):
            continue
        cells = [_clean_markdown_cell(cell) for cell in raw.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if all(re.fullmatch(r":?-{2,}:?", cell.replace(" ", "")) for cell in cells if cell):
            continue
        key, value = cells[0], cells[1]
        if not key or key in {"项目", "信息"} or value in {"信息", "---"}:
            continue
        pairs[key] = value
    return pairs


def _brief_meta_value(meta: dict[str, str], *labels: str) -> str:
    for label in labels:
        for key, value in meta.items():
            normalized_key = re.sub(r"[（(].*?[）)]", "", key).strip()
            if key == label or normalized_key == label or label in key:
                text = _clean_markdown_cell(value)
                if text:
                    return text
    return ""


def _extract_project_brief_prompt_block(text: str) -> str:
    heading_pattern = r"(?is)##\s*.*?(?:AI\s*生成的专属翻译提示词|专属翻译提示词|翻译提示词).*?```(?:[a-zA-Z0-9_-]+)?\s*(.*?)```"
    match = re.search(heading_pattern, text)
    if match:
        return match.group(1).strip()
    match = re.search(r"(?is)```(?:[a-zA-Z0-9_-]+)?\s*(.*?)```", text)
    return match.group(1).strip() if match else ""


def _is_project_brief_markdown_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return (
        "翻译提示词与项目元信息" in compact
        or ("AI生成的专属翻译提示词" in compact and "项目元信息" in compact)
        or ("专属翻译提示词" in compact and "|游戏类型|" in compact and "|翻译风格|" in compact)
    )


def _sanitize_project_brief_prompt(prompt: str) -> str:
    lines: list[str] = []
    inserted_term_rule = False
    for raw_line in str(prompt or "").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if re.search(r"(术语保持一致|核心术语|关键术语|术语清单|source\s*[:：].*target\s*[:：])", stripped, flags=re.IGNORECASE):
            if not inserted_term_rule:
                prefix_match = re.match(r"^(\s*(?:[-*]\s+|\d+[.、]\s*))", line)
                prefix = prefix_match.group(1) if prefix_match else ""
                lines.append(f"{prefix}{TERM_REFERENCE_RULE}")
                inserted_term_rule = True
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    if TERM_REFERENCE_RULE not in cleaned:
        cleaned = f"{cleaned}\n{TERM_REFERENCE_RULE}" if cleaned else TERM_REFERENCE_RULE
    return cleaned.strip()


def _project_brief_from_text(text: str) -> dict[str, Any] | None:
    prompt = _sanitize_project_brief_prompt(_extract_project_brief_prompt_block(text))
    meta = _markdown_table_pairs(text)
    if not prompt:
        return None
    core_meta_labels = {"游戏类型", "目标用户", "内容构成", "内容范围", "视觉与世界观", "世界观", "翻译风格", "重点注意", "语言资产", "信息来源"}
    matched_meta = {
        label
        for label in core_meta_labels
        if _brief_meta_value(meta, label)
    }
    if not _is_project_brief_markdown_text(text) and len(matched_meta) < 3:
        return None
    return {"prompt_text": prompt, "meta": meta}


def _primary_project_brief_material(material_packet: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [
        material for material in material_packet.get("materials", [])
        if isinstance(material, dict) and isinstance(material.get("project_brief"), dict)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: str(item.get("created_at") or ""))[-1]


def _brief_supplements_from_packet(material_packet: dict[str, Any], primary_artifact_id: str) -> dict[str, Any]:
    sources: list[str] = []
    visual_notes: list[str] = []
    language_assets: list[str] = []
    unsupported: list[str] = []
    for material in material_packet.get("materials", []):
        if not isinstance(material, dict) or str(material.get("artifact_id") or "") == primary_artifact_id:
            continue
        label = str(material.get("label") or material.get("filename") or "").strip()
        if label:
            sources.append(label)
        if material.get("language_table_candidate"):
            langs = "/".join(str(item) for item in material.get("detected_languages") or [])
            language_assets.append(f"{label}：{material.get('rows', 0)} 条；{langs}".strip("；"))
        if material.get("material_type") in {"image", "video"} and material.get("excerpt"):
            visual_notes.append(f"{label}：{str(material.get('excerpt'))[:300]}")
        if str(material.get("status") or "").startswith(("archived_only", "unsupported", "parse_failed")):
            unsupported.append(f"{label}：{material.get('status')}")
    return {
        "sources": sources,
        "language_assets": language_assets,
        "visual_notes": visual_notes,
        "unsupported": unsupported,
    }


def _apply_project_brief_markdown_profile(profile: dict[str, Any], material_packet: dict[str, Any]) -> dict[str, Any] | None:
    material = _primary_project_brief_material(material_packet)
    if not material:
        return None
    brief = material.get("project_brief") or {}
    meta = brief.get("meta") if isinstance(brief.get("meta"), dict) else {}
    prompt_text = _sanitize_project_brief_prompt(brief.get("prompt_text") or "")
    supplements = _brief_supplements_from_packet(material_packet, str(material.get("artifact_id") or ""))

    def meta_or_profile(*labels: str, profile_key: str, display_key: str = "") -> str:
        return _brief_meta_value(meta, *labels) or str(profile.get(display_key or profile_key) or profile.get(profile_key) or "").strip()

    language_assets = _brief_meta_value(meta, "语言资产")
    if not language_assets and supplements["language_assets"]:
        language_assets = "；".join(supplements["language_assets"][:4])
    if not language_assets:
        language_assets = str(profile.get("language_assets") or "")

    source_materials = _brief_meta_value(meta, "信息来源", "素材来源")
    if not source_materials and supplements["sources"]:
        source_materials = "；".join(supplements["sources"][:8])

    updated = {
        **profile,
        "game_type": meta_or_profile("游戏类型", profile_key="game_type", display_key="display_game_type"),
        "target_audience": meta_or_profile("目标用户", profile_key="target_audience", display_key="display_target_audience"),
        "content_scope": meta_or_profile("内容构成", "内容范围", profile_key="content_scope", display_key="display_content_scope"),
        "translation_style": meta_or_profile("翻译风格", "风格要求", profile_key="translation_style", display_key="display_translation_style"),
        "tone": meta_or_profile("视觉与世界观", "世界观", profile_key="tone", display_key="display_worldview"),
        "display_game_type": meta_or_profile("游戏类型", profile_key="game_type", display_key="display_game_type"),
        "display_target_audience": meta_or_profile("目标用户", profile_key="target_audience", display_key="display_target_audience"),
        "display_content_scope": meta_or_profile("内容构成", "内容范围", profile_key="content_scope", display_key="display_content_scope"),
        "display_worldview": meta_or_profile("视觉与世界观", "世界观", profile_key="tone", display_key="display_worldview"),
        "display_translation_style": meta_or_profile("翻译风格", "风格要求", profile_key="translation_style", display_key="display_translation_style"),
        "display_focus": _strip_term_noise(meta_or_profile("重点注意", "注意事项", profile_key="display_focus")),
        "language_assets": language_assets,
        "source_materials": [source_materials] if source_materials else profile.get("source_materials", []),
        "analysis_source": "md_primary",
        "analysis_warning": "",
        "brief_source": "md_primary",
        "brief_artifact_id": material.get("artifact_id"),
        "brief_prompt_text": prompt_text,
        "brief_meta": meta,
        "brief_supplements": supplements,
    }
    return updated


def _looks_english_heavy_text(value: Any) -> bool:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return False
    latin_letters = len(re.findall(r"[A-Za-z]", text))
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    if cjk_chars == 0 and latin_letters >= 8:
        return True
    return latin_letters > max(40, cjk_chars * 1.4)


def _prefer_chinese_display_value(provider_value: Any, seed_value: Any, fallback_value: Any = "") -> str:
    provider_text = re.sub(r"\s+", " ", str(provider_value or "")).strip()
    seed_text = re.sub(r"\s+", " ", str(seed_value or "")).strip()
    fallback_text = re.sub(r"\s+", " ", str(fallback_value or "")).strip()
    if provider_text and not _looks_english_heavy_text(provider_text):
        return provider_text
    if seed_text:
        return seed_text
    if fallback_text and not _looks_english_heavy_text(fallback_text):
        return fallback_text
    return provider_text or fallback_text


def _strip_term_noise(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    # Project prompt should not carry term lists; term hits are injected per task.
    text = re.sub(r"术语保持一致[：:][^。；;]*[。；;]?", "", text)
    text = re.sub(r"[^。；;]*核心术语[^。；;]*[。；;]?", "", text)
    text = re.sub(r"[^。；;]*术语优先一致性[^。；;]*[。；;]?", "", text)
    return re.sub(r"\s+", " ", text).strip("；;。 ")


def _is_stale_project_prompt_text(value: Any) -> bool:
    text = str(value or "")
    if not text.strip():
        return False
    stale_patterns = (
        r"核心术语",
        r"术语保持一致[：:]",
        r"项目术语以术语表为准",
        r"已有.+译文代表项目历史用法",
        r"\{\s*['\"]?source['\"]?\s*:",
        r"['\"]target['\"]\s*:",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in stale_patterns)


def _project_analysis_compact_evidence(material_packet: dict[str, Any]) -> dict[str, Any]:
    materials: list[dict[str, Any]] = []
    for material in material_packet.get("materials", []):
        if not isinstance(material, dict):
            continue
        materials.append(
            {
                "label": material.get("label"),
                "filename": material.get("filename"),
                "material_type": material.get("material_type"),
                "status": material.get("status"),
                "rows": material.get("rows"),
                "sheets": material.get("sheets", [])[:5] if isinstance(material.get("sheets"), list) else [],
                "detected_languages": material.get("detected_languages") or [],
                "language_table_candidate": bool(material.get("language_table_candidate")),
                "headings": material.get("headings", [])[:8] if isinstance(material.get("headings"), list) else [],
                "table_rows": material.get("table_rows", [])[:16] if isinstance(material.get("table_rows"), list) else [],
                "samples": material.get("samples", [])[:12] if isinstance(material.get("samples"), list) else [],
                "visual_summary": material.get("visual_summary") or "",
                "excerpt": _cap_context_text(material.get("excerpt", ""), 1200, "material excerpt"),
            }
        )
    return {
        "summary": material_packet.get("summary") or {},
        "language_table_candidates": material_packet.get("language_table_candidates") or [],
        "warnings": material_packet.get("warnings") or [],
        "materials": materials,
    }


def _language_table_signal_seed(material_packet: dict[str, Any]) -> dict[str, str]:
    source_samples: list[str] = []
    translated_rows = 0
    total_rows = 0
    for material in material_packet.get("materials", []):
        if not isinstance(material, dict):
            continue
        total_rows += int(material.get("rows") or 0)
        for sample in material.get("samples") or []:
            if not isinstance(sample, dict):
                continue
            source = str(sample.get("source") or "").strip()
            if source:
                source_samples.append(source)
            translated_rows += sum(1 for key, value in sample.items() if key not in {"sheet", "source"} and str(value or "").strip())
    text = " ".join(source_samples)[:20000]
    if not text:
        return {}
    groups = {
        "地狱监狱经营 SLG": ("地狱", "监狱", "灵魂", "审判", "净化", "恶魔", "罪", "牢房", "囚犯", "典狱"),
        "科幻战机 / 飞行射击 / RPG养成": ("战机", "导弹", "僚机", "机甲", "飞行", "射击", "战力", "装备", "英雄", "技能"),
        "基地经营 / 战争策略 SLG": ("基地", "联盟", "行军", "集结", "攻城", "建筑", "资源", "士兵", "战争", "排行榜"),
        "合成经营 / 休闲剧情": ("合成", "订单", "生产", "仓库", "顾客", "装修", "花店", "剧情", "修复", "收集"),
    }
    scored: list[tuple[int, str]] = []
    for label, keywords in groups.items():
        score = sum(text.count(keyword) for keyword in keywords)
        if score:
            scored.append((score, label))
    scored.sort(reverse=True)
    if not scored:
        return {}
    label = scored[0][1]
    if label == "地狱监狱经营 SLG":
        target = "喜欢暗黑幽默、黑色题材、基地经营、英雄养成和联盟战斗的移动端 SLG 玩家"
        focus = "UI、任务、建筑、英雄、技能、道具、活动、联盟、战斗、邮件、剧情和新手引导"
        style = "UI 要短促直接，剧情自然讽刺，系统名严谨统一；功能说明不能为了玩梗牺牲清晰度"
        tone = "暗红地狱、工业监狱、恶魔管理者、审判/净化设备等黑色幽默世界观"
    elif label.startswith("科幻战机"):
        target = "偏中重度、喜欢战机养成、战斗数值、装备强化和活动推进的移动端玩家"
        focus = "战机、导弹、射击、弹幕、英雄、装备、技能、属性、战力成长、基地系统和活动奖励"
        style = "冷静利落，偏科幻军事；战机、装备、导弹、技能和战斗数值要专业清晰"
        tone = "科幻军事、战斗推进、装备成长"
    elif label.startswith("基地经营"):
        target = "喜欢基地建设、联盟竞争、战斗推进和长期成长的移动端 SLG 玩家"
        focus = "建筑、升级、资源、联盟、行军、集结、战斗、活动、排行榜和邮件系统"
        style = "系统名统一，按钮和提示短句清楚；战斗、联盟、资源相关表达保持策略游戏常用说法"
        tone = "策略战争、基地经营、联盟竞争"
    else:
        target = "喜欢轻策略、收集、订单推进和长期经营成长的休闲玩家"
        focus = "合成、订单、生产、仓库、装修、活动、奖励和剧情文本"
        style = "轻松自然，UI 短句清楚；经营和剧情文本保持温和、生活化但不啰嗦"
        tone = "休闲经营、轻剧情、成长收集"
    return {
        "display_game_type": label,
        "display_target_audience": target,
        "display_content_scope": focus,
        "display_worldview": tone,
        "display_translation_style": style,
        "language_assets": f"{total_rows} 条文本，样本中已有目标语 {translated_rows} 条。" if total_rows else "",
    }


def _project_analysis_provider_prompt(project: dict[str, Any], intro: str, asset_notes: list[str], profile: dict[str, Any], material_packet: dict[str, Any]) -> str:
    compact_evidence = _project_analysis_compact_evidence(material_packet)
    return (
        "你正在为游戏本地化项目做真实资料分析，不是套模板。\n"
        "Return strict JSON only. No markdown fences or prose.\n"
        "必须只基于 evidence packet、项目 intro 和参考资料；资料没有支持的信息写入 missing_info，不要编造。\n"
        "display_* 字段必须用中文短句，给前端和译员看；执行字段可用目标语言或英文，给模型翻译/QA 使用。\n"
        "不要输出术语清单、source/target JSON、客套话或资料处理流水账；术语会在翻译任务中通过随附术语表单独提供。\n"
        "Required JSON fields: game_type, target_audience, content_scope, translation_style, tone, "
        "display_game_type, display_target_audience, display_content_scope, display_worldview, "
        "display_translation_style, display_focus, confidence, missing_info.\n\n"
        f"Project name: {project.get('name', '')}\n"
        f"Project type: {project.get('type', '')}\n"
        f"Project description: {project.get('description', '')}\n"
        f"Target language: {profile.get('target_language_name', profile.get('target_language', 'en'))}\n"
        f"User intro:\n{intro}\n\n"
        f"Reference material notes:\n{json.dumps(asset_notes, ensure_ascii=False, indent=2)}\n\n"
        f"Evidence packet:\n{json.dumps(compact_evidence, ensure_ascii=False, indent=2)}\n\n"
        f"Evidence context:\n{_cap_context_text(material_packet.get('context', ''), 3500, 'project analysis evidence')}\n\n"
        f"Template baseline:\n{json.dumps({key: profile.get(key, '') for key in ('game_type', 'target_audience', 'content_scope', 'translation_style', 'tone')}, ensure_ascii=False, indent=2)}"
    )


def _apply_project_analysis_provider(project: dict[str, Any], intro: str, asset_notes: list[str], profile: dict[str, Any], material_packet: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    provider = normalize_provider_name(settings.get("provider"))
    if provider not in REAL_PROVIDERS or not settings.get("api_key"):
        return profile
    prompt = _cap_context_text(_project_analysis_provider_prompt(project, intro, asset_notes, profile, material_packet), 12000, "project analysis")
    payload = _parse_semantic_qa_payload(_call_semantic_provider(settings, prompt))
    if not isinstance(payload, dict):
        raise ValueError("project analysis provider must return a JSON object")
    updates: dict[str, Any] = {}
    seed = _display_profile_seed_from_packet(material_packet)
    for key in (
        "game_type", "target_audience", "content_scope", "translation_style", "tone",
        "confidence",
    ):
        value = str(payload.get(key) or "").strip()
        if value:
            updates[key] = value
    display_fallbacks = {
        "display_game_type": updates.get("game_type") or profile.get("game_type"),
        "display_target_audience": updates.get("target_audience") or profile.get("target_audience"),
        "display_content_scope": updates.get("content_scope") or profile.get("content_scope"),
        "display_worldview": updates.get("tone") or profile.get("tone"),
        "display_translation_style": updates.get("translation_style") or profile.get("translation_style"),
        "display_focus": profile.get("display_focus") or "",
    }
    for key, fallback in display_fallbacks.items():
        value = _prefer_chinese_display_value(payload.get(key), seed.get(key), fallback)
        if key == "display_focus":
            value = _strip_term_noise(value)
        if value:
            updates[key] = value
    missing_info = payload.get("missing_info")
    if isinstance(missing_info, list):
        updates["missing_info"] = [str(item).strip() for item in missing_info if str(item).strip()]
    elif str(missing_info or "").strip():
        updates["missing_info"] = [str(missing_info).strip()]
    return {
        **profile,
        **updates,
        "analysis_source": "provider",
        "analysis_provider": provider,
        "analysis_model": str(settings.get("model") or ""),
        "analysis_warning": "",
    }


def _project_prompt_from_profile(profile: dict[str, Any]) -> str:
    spec = language_spec(profile.get("target_language") or "en")
    project_name = str(profile.get("project_name") or "当前项目").strip()
    game_type = re.sub(r"\s+", " ", str(profile.get("game_type") or profile.get("display_game_type") or "游戏本地化项目")).strip()
    content_scope = re.sub(r"\s+", " ", str(profile.get("content_scope") or profile.get("display_content_scope") or "UI、系统、任务、道具、活动和剧情文本")).strip()
    style = re.sub(r"\s+", " ", str(profile.get("translation_style") or profile.get("display_translation_style") or "短句清晰、自然准确，适合游戏 UI")).strip()
    tone = re.sub(r"\s+", " ", str(profile.get("tone") or profile.get("display_worldview") or "")).strip()
    focus = _strip_term_noise(profile.get("display_focus") or "")
    return (
        f"项目：《{project_name}》；目标语言：{spec.label}（{spec.prompt_name}）。\n"
        f"题材定位：{game_type}。\n"
        f"内容范围：{content_scope}。\n"
        f"翻译风格：{style}。\n"
        + (f"世界观/语气：{tone}。\n" if tone else "")
        + (f"重点注意：{focus}。\n" if focus else "")
        + "术语译法以本次任务随附术语表、行级 term_hits 和译文归档命中为准，不要自行改名。\n"
        + "保留变量、数字、换行、颜色标签、HTML/富文本标签和占位符，例如 {0}、%s、<color>。\n"
        + "无法确认的专有名词用 [TBD] 标记，不要编造设定。\n"
        + "输出协议：只返回 JSONL，每行包含 id 和 translation。"
    )



def _project_prompt_display_zh(profile: dict[str, Any]) -> str:
    spec = language_spec(profile.get("target_language") or "en")
    project_name = str(profile.get("project_name") or "\u5f53\u524d\u9879\u76ee").strip()
    source_text = " ".join(str(item or "") for item in profile.get("asset_notes") or [])

    def table_value(*labels: str) -> str:
        for label in labels:
            pattern = rf"\|\s*{re.escape(label)}(?:（[^|]*）)?\s*\|\s*([^|]+?)\s*\|"
            match = re.search(pattern, source_text)
            if match:
                return match.group(1).strip()
        return ""

    def first_text(*values: Any) -> str:
        for value in values:
            text = re.sub(r"\s+", " ", str(value or "")).strip()
            if text:
                return text
        return ""

    def sentence(label: str, value: str) -> str:
        value = value.strip().rstrip("。；;")
        return f"{label}：{value}。" if value else ""

    game_type = first_text(profile.get("display_game_type"), table_value("游戏类型"), profile.get("game_type"))
    target_audience = first_text(profile.get("display_target_audience"), table_value("目标用户"), profile.get("target_audience"))
    content_scope = first_text(profile.get("display_content_scope"), table_value("内容构成", "内容范围"), profile.get("content_scope"))
    worldview = first_text(profile.get("display_worldview"), table_value("视觉与世界观", "世界观"), profile.get("tone"))
    style = first_text(profile.get("display_translation_style"), table_value("翻译风格", "风格要求"), profile.get("translation_style"))
    focus = _strip_term_noise(first_text(profile.get("display_focus"), table_value("重点注意", "注意事项")))
    lines = [
        f"\u4f60\u6b63\u5728\u5904\u7406\u300a{project_name}\u300b\u7684\u6e38\u620f\u672c\u5730\u5316\uff0c\u76ee\u6807\u8bed\u8a00\uff1a{spec.label}\u3002",
        sentence("项目定位", game_type),
        sentence("目标用户", target_audience),
        sentence("内容范围", content_scope),
        sentence("世界观/语气", worldview),
        sentence("风格要求", style),
        sentence("重点注意", focus),
        "\u672f\u8bed\u8bd1\u6cd5\u4ee5\u672c\u6b21\u4efb\u52a1\u968f\u9644\u672f\u8bed\u8868\u3001\u884c\u7ea7 term_hits \u548c\u8bd1\u6587\u5f52\u6863\u547d\u4e2d\u4e3a\u51c6\u3002",
        "\u5fc5\u987b\u4fdd\u7559\u53d8\u91cf\u3001\u6570\u5b57\u3001\u6362\u884c\u3001\u989c\u8272\u6807\u7b7e\u3001HTML/\u5bcc\u6587\u672c\u6807\u7b7e\u548c\u5360\u4f4d\u7b26\uff0c\u4f8b\u5982 {0}\u3001%s\u3001<color>\u3002",
        "\u65e0\u6cd5\u786e\u8ba4\u7684\u4e13\u6709\u540d\u8bcd\u6216\u4fe1\u606f\u7f3a\u53e3\u7528 [TBD] \u6807\u8bb0\uff0c\u4e0d\u8981\u81ea\u884c\u7f16\u9020\u8bbe\u5b9a\u3002",
    ]
    return "\n".join(str(line).strip() for line in lines if str(line).strip())


def _project_display_prompt_from_profile(profile: dict[str, Any]) -> str:
    if profile.get("brief_source") == "md_primary" and str(profile.get("brief_prompt_text") or "").strip():
        return _sanitize_project_brief_prompt(str(profile.get("brief_prompt_text") or ""))
    return _project_prompt_display_zh(profile)


def _project_execution_prompt_from_profile(profile: dict[str, Any]) -> str:
    if profile.get("brief_source") == "md_primary" and str(profile.get("brief_prompt_text") or "").strip():
        prompt = _sanitize_project_brief_prompt(str(profile.get("brief_prompt_text") or ""))
        if "输出协议" not in prompt and "JSONL" not in prompt.upper():
            prompt += "\n输出协议：只返回 JSONL，每行包含 id 和 translation。"
        return prompt
    return _project_prompt_from_profile(profile)


def _project_brief_markdown(profile: dict[str, Any], prompt: str) -> str:
    game_type = str(profile.get("display_game_type") or profile.get("game_type") or "")
    target_audience = str(profile.get("display_target_audience") or profile.get("target_audience") or "")
    content_scope = str(profile.get("display_content_scope") or profile.get("content_scope") or "")
    worldview = str(profile.get("display_worldview") or profile.get("tone") or "")
    translation_style = str(profile.get("display_translation_style") or profile.get("translation_style") or "")
    focus = str(profile.get("display_focus") or "")
    source_materials = "；".join(str(item) for item in (profile.get("source_materials") or []) if str(item).strip())
    warning = str(profile.get("analysis_warning") or "")
    return (
        f"# {profile['project_name']} 翻译提示词与项目元信息\n\n"
        "## 🤖 AI 生成的专属翻译提示词\n\n"
        "```\n"
        f"{prompt}\n"
        "```\n\n"
        "## 📌 项目元信息\n\n"
        "| 项目 | 信息 |\n"
        "| --- | --- |\n"
        f"| 游戏类型 | {game_type} |\n"
        f"| 目标用户 | {target_audience} |\n"
        f"| 内容构成 | {content_scope} |\n"
        f"| 视觉与世界观 | {worldview or '-'} |\n"
        f"| 翻译风格 | {translation_style} |\n"
        f"| 重点注意 | {focus or '-'} |\n"
        f"| 信息来源 | {source_materials or '-'} |\n"
        f"| 语言资产 | {profile['language_assets']} |\n"
        f"| 分析状态 | {warning or profile.get('analysis_source', 'template')} |\n"
        f"| 生成日期 | {profile['generated_date']} |\n"
    )


def _project_analysis_report_markdown(profile: dict[str, Any], material_packet: dict[str, Any]) -> str:
    summary = material_packet.get("summary") or {}
    warnings = material_packet.get("warnings") or []
    materials = material_packet.get("materials") or []
    rows = [
        "# 项目资料 AI 分析报告",
        "",
        f"- 分析状态：{profile.get('analysis_source', 'template')}",
        f"- 模型：{profile.get('analysis_provider', '-')}/{profile.get('analysis_model', '-')}",
        f"- 资料总数：{summary.get('total', 0)}",
        f"- 已读取：{summary.get('parsed', 0)}",
        f"- 语言表候选：{summary.get('language_table_candidates', 0)}",
        f"- 图片资料：{summary.get('images', 0)}",
    ]
    if profile.get("analysis_warning"):
        rows.append(f"- 提示：{profile['analysis_warning']}")
    if warnings:
        rows.extend(["", "## 未完全分析的资料", *[f"- {warning}" for warning in warnings]])
    rows.append("")
    rows.append("## 资料读取明细")
    for material in materials:
        rows.append(f"- {material.get('label')}: {material.get('status')}；{material.get('note', '')}")
    return "\n".join(rows).strip() + "\n"


def _save_generated_project_harness(project: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    current = read_project_harness(project["id"])
    metadata = dict(current.get("project_metadata") or {})
    metadata.update(
        {
            "game_type": profile["game_type"],
            "target_language": profile["target_language"],
            "content_scope": profile["content_scope"],
            "language_assets": profile["language_assets"],
            "source_materials": profile.get("source_materials", []),
            "generated_from": "project_analysis",
        }
    )
    return write_project_harness(
        project["id"],
        {
            "project_metadata": metadata,
            "style_guidance": profile["translation_style"],
            "target_audience": profile["target_audience"],
            "tone": profile["tone"],
        },
    )


def _profile_material_summary(material_packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": material_packet.get("summary") or {},
        "materials": [
            {
                "artifact_id": material.get("artifact_id"),
                "label": material.get("label"),
                "material_type": material.get("material_type"),
                "status": material.get("status"),
                "rows": material.get("rows"),
                "detected_languages": material.get("detected_languages") or [],
                "language_table_candidate": bool(material.get("language_table_candidate")),
                "project_brief_candidate": bool(material.get("project_brief_candidate")),
                "warning": material.get("warning") or "",
            }
            for material in material_packet.get("materials", [])
            if isinstance(material, dict)
        ],
        "language_table_candidates": material_packet.get("language_table_candidates") or [],
        "warnings": material_packet.get("warnings") or [],
    }

__all__ = [name for name in globals() if not name.startswith("__")]
