from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook

from . import db
from .config import DATA_ROOT, GLOSSARY_ROOT, LOCALIZATION_ROOT, load_settings
from .providers import translate_batch


HARNESS_SCHEMA_VERSION = 1
GLOBAL_HARNESS_CONTRACT: dict[str, Any] = {
    "source": "global_harness",
    "workpack": "translation_workpack.jsonl",
    "response_protocol": "jsonl:{id:int,translation:str}",
    "hard_gates": ["id", "placeholder", "tag", "newline", "input_fingerprint"],
    "qa_sources": ["workflow/localization/utils/quality_harness.py", "workflow/localization/fixtures/quality_regression.json"],
}


def project_dir(project_id: str) -> Path:
    path = DATA_ROOT / "projects" / project_id
    path.mkdir(parents=True, exist_ok=True)
    for child in ("uploads", "profile", "glossary", "runs", "assets"):
        (path / child).mkdir(exist_ok=True)
    return path


def run_dir(run_id: str) -> Path:
    path = DATA_ROOT / "runs" / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_project_harness(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": HARNESS_SCHEMA_VERSION,
        "source": "project_harness",
        "project_id": project["id"],
        "project_name": project["name"],
        "project_metadata": {},
        "style_guidance": "",
        "target_audience": "",
        "tone": "",
        "forbidden_translations": [],
        "fixed_terms": [],
        "hard_rules": [],
        "soft_rules": [],
        "reference_examples": [],
        "manual_fixes": [],
        "qa_summary": {},
        "updated_at": "",
    }


def project_harness_path(project_id: str) -> Path:
    return project_dir(project_id) / "profile" / "project_harness.json"


def read_project_harness(project_id: str) -> dict[str, Any]:
    project = db.get_project(project_id)
    default = default_project_harness(project)
    path = project_harness_path(project_id)
    if not path.exists():
        return default
    payload = json.loads(path.read_text(encoding="utf-8"))
    merged = {**default, **payload}
    merged["project_id"] = project_id
    merged["project_name"] = project["name"]
    merged["schema_version"] = HARNESS_SCHEMA_VERSION
    return _sanitize_harness(merged)


def write_project_harness(project_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    payload = read_project_harness(project_id)
    for key, value in updates.items():
        if value is not None:
            payload[key] = value
    payload["updated_at"] = db.now_iso()
    payload = _sanitize_harness(payload)
    path = project_harness_path(project_id)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def harness_overview(project_id: str) -> dict[str, Any]:
    return {
        "global_harness": GLOBAL_HARNESS_CONTRACT,
        "project_harness": read_project_harness(project_id),
        "boundary": (
            "global_harness stores reusable workflow contracts and gates; "
            "project_harness stores this project's private requirements only."
        ),
    }


def _workbook_text_stats(path: Path) -> dict[str, int]:
    try:
        wb = load_workbook(path, read_only=True, data_only=False)
        ws = wb.active
        headers = [str(cell.value or "").strip() for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        lowered = [header.lower() for header in headers]
        source_idx = next(
            (idx for idx, header in enumerate(lowered) if header in {"cn", "source", "原文", "中文"}),
            None,
        )
        target_idx = next(
            (idx for idx, header in enumerate(lowered) if header in {"en", "target", "translation", "译文", "英文"}),
            None,
        )
        source_rows = 0
        translated_rows = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            if source_idx is not None and row[source_idx] not in (None, ""):
                source_rows += 1
            if target_idx is not None and row[target_idx] not in (None, ""):
                translated_rows += 1
        wb.close()
        return {"source_rows": source_rows, "translated_rows": translated_rows}
    except Exception:
        return {"source_rows": 0, "translated_rows": 0}


def _language_assets_summary(project_id: str) -> str:
    candidates = [
        *db.list_artifacts(project_id=project_id, role="translation_workbook"),
        *db.list_artifacts(project_id=project_id, role="language_source"),
    ]
    best = {"source_rows": 0, "translated_rows": 0}
    for artifact in candidates:
        path = Path(str(artifact.get("path") or ""))
        if path.suffix.lower() != ".xlsx" or not path.exists():
            continue
        stats = _workbook_text_stats(path)
        if stats["source_rows"] > best["source_rows"]:
            best = stats
        elif stats["translated_rows"] > best["translated_rows"]:
            best["translated_rows"] = stats["translated_rows"]
    if best["source_rows"]:
        return f"{best['source_rows']} 条文本，已有英文 {best['translated_rows']} 条。"
    return "暂未统计语言表行数。"


def _project_material_labels(project_id: str) -> list[str]:
    labels: list[str] = []
    for role in ("glossary_source", "language_source", "translation_workbook"):
        for artifact in db.list_artifacts(project_id=project_id, role=role):
            label = str(artifact.get("label") or "").strip()
            if label and label not in labels:
                labels.append(label)
    return labels


def _is_warplane_project(project: dict[str, Any], intro: str, material_labels: list[str]) -> bool:
    text = " ".join(
        [
            str(project.get("name") or ""),
            str(project.get("type") or ""),
            str(project.get("description") or ""),
            intro,
            *material_labels,
        ]
    )
    return any(token in text for token in ("战机", "飞行射击", "导弹", "装备", "Warplane", "warplane"))


def _build_project_profile(project: dict[str, Any], intro: str, asset_notes: list[str]) -> dict[str, Any]:
    material_labels = _project_material_labels(project["id"])
    description = project.get("description", "") or intro
    is_warplane = _is_warplane_project(project, intro, material_labels)
    if is_warplane:
        game_type = "科幻战机 / 飞行射击 / RPG养成"
        target_audience = "偏中重度、喜欢战机养成、战斗数值、装备强化和活动推进的移动端玩家。"
        content_scope = "战机、导弹、射击、弹幕等战斗内容；英雄、装备、技能、属性和战力成长；建造、升级、采集、生产等基地系统；角色剧情对话；活动、礼包和奖励。"
        translation_style = "UI/玩法精简适配移动端；剧情自然、地道、通顺，参考美剧日常对白；整体语气冷静、利落、偏科幻军事；战机、装备、导弹、技能和战斗数值要专业清晰，避免可爱化、生活化或过度口语化。"
        tone = "冷静、利落、偏科幻军事"
    else:
        game_type = project.get("type", "") or "游戏本地化项目"
        target_audience = "目标语区游戏玩家；以当前项目描述和参考素材为准。"
        content_scope = description or "UI、系统、任务、道具、活动和剧情文本。"
        translation_style = "准确翻译为自然英文；UI/按钮/任务短句清晰；剧情对话自然但不改设定；术语以项目术语表为准；保留变量、占位符、富文本标签、数字和换行。"
        tone = "自然、准确、游戏 UI 友好"
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
        "language_assets": _language_assets_summary(project["id"]),
        "target_language": "en",
        "tone": tone,
        "generated_date": db.now_iso()[:10],
    }


def _project_prompt_from_profile(profile: dict[str, Any]) -> str:
    return (
        f"你是一位资深游戏本地化译者，正在翻译《{profile['project_name']}》这款{profile['game_type']}游戏。\n"
        "译文需符合以下要求：\n"
        "1. 游戏内容/UI/玩法说明尽量精简，适配移动游戏按钮、弹窗、任务、道具和奖励说明；\n"
        "2. 剧情对话必须自然、地道、通顺，保留角色语气、冲突、幽默和情绪，不要逐字直译；\n"
        "3. 整体语气冷静、利落、偏科幻军事；战机、装备、导弹、技能和战斗数值要专业清晰，避免可爱化、生活化或过度口语化；\n"
        "4. 关键术语以随附术语表为准，EN 为标准译法，EN2 为项目中稳定出现的手动适配译法；\n"
        "5. 已有英文译文代表项目历史用法；如现有译法不自然，可以优化，但不要破坏已固定的系统术语；\n"
        "6. 保留所有游戏代码、变量、数字、换行、颜色标签、HTML/富文本标签和占位符，如 {0}、%s、<color> 等；\n"
        "7. 无法确认的专有名词或信息缺口用 [TBD] 标记，不要自行编造设定。\n"
        "输出协议：只返回 JSONL，每行包含 id 和 translation。"
    )


def _project_brief_markdown(profile: dict[str, Any], prompt: str) -> str:
    return (
        f"# {profile['project_name']} 翻译提示词与项目元信息\n\n"
        "## 🤖 AI 生成的专属翻译提示词\n\n"
        "```\n"
        f"{prompt}\n"
        "```\n\n"
        "## 📌 项目元信息\n\n"
        "| 项目 | 信息 |\n"
        "| --- | --- |\n"
        f"| 游戏类型 | {profile['game_type']} |\n"
        f"| 目标用户 | {profile['target_audience']} |\n"
        f"| 内容构成 | {profile['content_scope']} |\n"
        f"| 翻译风格 | {profile['translation_style']} |\n"
        f"| 语言资产 | {profile['language_assets']} |\n"
        f"| 生成日期 | {profile['generated_date']} |\n"
    )


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


def write_project_prompt(project: dict[str, Any], intro: str, asset_notes: list[str]) -> tuple[Path, Path, Path, str]:
    root = project_dir(project["id"]) / "profile"
    profile = _build_project_profile(project, intro, asset_notes)
    prompt = _project_prompt_from_profile(profile)
    _save_generated_project_harness(project, profile)
    profile_path = root / "project_profile.json"
    prompt_path = root / "translation_prompt.txt"
    brief_path = root / "project_brief.md"
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    prompt_path.write_text(prompt, encoding="utf-8")
    brief_path.write_text(_project_brief_markdown(profile, prompt), encoding="utf-8")
    db.update_project(project["id"], {"profile": profile, "prompt_text": prompt})
    return profile_path, prompt_path, brief_path, prompt


def compile_project_harness_prompt(project: dict[str, Any], base_prompt: str, output_dir: Path) -> tuple[Path, Path, str, dict[str, Any]]:
    harness = read_project_harness(project["id"])
    parts = [base_prompt.strip()]
    project_parts = _project_harness_prompt_parts(harness)
    if project_parts:
        parts.append(
            "Project Harness (project-specific; apply only to this project, do not generalize):\n"
            + "\n".join(project_parts)
        )
    compiled = "\n\n".join(part for part in parts if part)
    prompt_path = output_dir / "compiled_project_harness_prompt.txt"
    snapshot_path = output_dir / "project_harness_snapshot.json"
    snapshot = {
        "global_harness": GLOBAL_HARNESS_CONTRACT,
        "project_harness": harness,
        "summary": _harness_summary(harness),
    }
    prompt_path.write_text(compiled, encoding="utf-8")
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return prompt_path, snapshot_path, compiled, snapshot


def create_project_glossary_snapshot(project_id: str, run_id: str, output_dir: Path | None = None) -> dict[str, Any]:
    output = output_dir or run_dir(run_id) / "snapshots"
    output.mkdir(parents=True, exist_ok=True)
    path = output / "project_glossary_snapshot.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Glossary"
    ws.append(["ID", "CN", "EN", "EN2", "分类", "备注"])
    terms = db.list_glossary_terms(project_id)
    for term in reversed(terms):
        ws.append(_glossary_export_row(term))
    wb.save(path)
    wb.close()
    return db.add_artifact(
        project_id,
        "Project glossary snapshot",
        path,
        "glossary_snapshot",
        run_id=run_id,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        origin="generated",
        metadata={"term_count": len(terms), "source": "project_glossary"},
    )


def create_prompt_and_harness_snapshots(project_id: str, run_id: str, output_dir: Path | None = None) -> dict[str, Any]:
    project = db.get_project(project_id)
    output = output_dir or run_dir(run_id) / "snapshots"
    output.mkdir(parents=True, exist_ok=True)
    prompt_path = project_dir(project_id) / "profile" / "translation_prompt.txt"
    if not prompt_path.exists():
        write_project_prompt(project, project.get("description", ""), [])
    base_prompt = prompt_path.read_text(encoding="utf-8")
    compiled_path, harness_path, compiled_prompt, harness_snapshot = compile_project_harness_prompt(project, base_prompt, output)
    prompt_artifact = db.add_artifact(
        project_id,
        "Prompt snapshot",
        compiled_path,
        "prompt_snapshot",
        run_id=run_id,
        mime="text/plain",
        origin="generated",
        metadata={"source": "project_prompt_and_harness"},
    )
    harness_artifact = db.add_artifact(
        project_id,
        "Project harness snapshot",
        harness_path,
        "project_harness_snapshot",
        run_id=run_id,
        mime="application/json",
        origin="generated",
        metadata={"source": "project_harness"},
    )
    return {
        "prompt": compiled_prompt,
        "prompt_artifact": prompt_artifact,
        "harness_artifact": harness_artifact,
        "harness_snapshot": harness_snapshot,
        "prompt_path": compiled_path,
        "harness_path": harness_path,
    }


def analyze_assets(artifact_ids: list[str], settings: dict[str, Any]) -> list[str]:
    support = settings.get("multimodal", {})
    notes: list[str] = []
    for artifact_id in artifact_ids:
        artifact = db.get_artifact(artifact_id)
        suffix = Path(artifact["path"]).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            state = "analyzed" if support.get("images") else "archived_only:image_not_supported"
        elif suffix == ".pdf":
            state = "analyzed_text_first" if support.get("pdf") else "archived_only:pdf_not_supported"
        elif suffix in {".mp4", ".mov", ".mkv"}:
            state = "analyzed" if support.get("video") else "archived_only:video_not_supported"
        elif suffix in {".mp3", ".wav", ".m4a"}:
            state = "analyzed" if support.get("audio") else "archived_only:audio_not_supported"
        else:
            state = "archived_only:unknown_type"
        notes.append(f"{artifact['label']}={state}")
    return notes


def _sanitize_harness(payload: dict[str, Any]) -> dict[str, Any]:
    text_fields = ("style_guidance", "target_audience", "tone")
    list_fields = (
        "forbidden_translations",
        "fixed_terms",
        "hard_rules",
        "soft_rules",
        "reference_examples",
        "manual_fixes",
    )
    for key in text_fields:
        payload[key] = str(payload.get(key) or "").strip()
    for key in list_fields:
        value = payload.get(key)
        payload[key] = value if isinstance(value, list) else []
    cleaned_fixed_terms = []
    for item in payload.get("fixed_terms", []):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        if not source or not target:
            continue
        if all(ch in "?�" or ch.isspace() for ch in source):
            continue
        cleaned_fixed_terms.append(item)
    payload["fixed_terms"] = cleaned_fixed_terms
    if not isinstance(payload.get("project_metadata"), dict):
        payload["project_metadata"] = {}
    if not isinstance(payload.get("qa_summary"), dict):
        payload["qa_summary"] = {}
    return payload


def _project_harness_prompt_parts(harness: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    if harness.get("target_audience"):
        parts.append(f"- Target audience: {harness['target_audience']}")
    if harness.get("tone"):
        parts.append(f"- Tone: {harness['tone']}")
    if harness.get("style_guidance"):
        parts.append(f"- Style guidance: {harness['style_guidance']}")
    forbidden = [str(item).strip() for item in harness.get("forbidden_translations", []) if str(item).strip()]
    if forbidden:
        parts.append("- Forbidden translations: " + "; ".join(forbidden))
    fixed_terms = []
    for item in harness.get("fixed_terms", []):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", "")).strip()
        target = str(item.get("target", "")).strip()
        if source and target:
            fixed_terms.append(f"{source} => {target}")
    if fixed_terms:
        parts.append("- Fixed terms: " + "; ".join(fixed_terms))
    for label, key in (("Hard project rules", "hard_rules"), ("Soft project rules", "soft_rules")):
        rules = [
            str(rule.get("description") or rule.get("label") or "").strip()
            for rule in harness.get(key, [])
            if isinstance(rule, dict) and rule.get("enabled", True) and str(rule.get("description") or rule.get("label") or "").strip()
        ]
        if rules:
            parts.append(f"- {label}: " + "; ".join(rules))
    examples = []
    for item in harness.get("reference_examples", []):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", "")).strip()
        target = str(item.get("target", "")).strip()
        if source and target:
            examples.append(f"{source} => {target}")
    if examples:
        parts.append("- Accepted examples: " + "; ".join(examples[:10]))
    return parts


def _harness_summary(harness: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "project_harness",
        "schema_version": harness.get("schema_version", HARNESS_SCHEMA_VERSION),
        "updated_at": harness.get("updated_at", ""),
        "style_guidance": bool(harness.get("style_guidance")),
        "hard_rules": len(harness.get("hard_rules", [])),
        "soft_rules": len(harness.get("soft_rules", [])),
        "fixed_terms": len(harness.get("fixed_terms", [])),
        "forbidden_translations": len(harness.get("forbidden_translations", [])),
        "reference_examples": len(harness.get("reference_examples", [])),
    }


def copy_upload(project_id: str, source_path: Path, label: str, kind: str) -> dict[str, Any]:
    destination_dir = project_dir(project_id) / "uploads"
    destination = destination_dir / source_path.name
    shutil.copy2(source_path, destination)
    return db.add_artifact(project_id, label=label, path=destination, kind=kind)


def run_subprocess(args: list[str], cwd: Path, run_id: str) -> subprocess.CompletedProcess[str]:
    db.add_event(run_id, "running: " + " ".join(args))
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(
        args,
        cwd=str(cwd),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if proc.stdout:
        db.add_event(run_id, proc.stdout.strip())
    if proc.stderr:
        db.add_event(run_id, proc.stderr.strip(), level="warn")
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(args)}\n{proc.stderr or proc.stdout}")
    return proc


def run_subprocess_allow_failure(args: list[str], cwd: Path, run_id: str) -> subprocess.CompletedProcess[str]:
    db.add_event(run_id, "running: " + " ".join(args))
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(
        args,
        cwd=str(cwd),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if proc.stdout:
        db.add_event(run_id, proc.stdout.strip())
    if proc.stderr:
        db.add_event(run_id, proc.stderr.strip(), level="warn")
    return proc


def parse_key_output(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in text.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def extract_glossary(project_id: str, request: Any) -> dict[str, Any]:
    project = db.get_project(project_id)
    artifact = db.get_artifact(request.input_artifact_id)
    material_artifact_ids = list(getattr(request, "project_material_artifact_ids", []) or [])
    project_notes = [str(note).strip() for note in getattr(request, "project_notes", []) or [] if str(note).strip()]
    material_notes = analyze_assets(material_artifact_ids, load_settings()) if material_artifact_ids else []
    run = db.insert_run(
        project_id,
        kind="glossary",
        language="en",
        metadata={
            "input_artifact_id": request.input_artifact_id,
            "project_material_artifact_ids": material_artifact_ids,
            "project_notes": project_notes,
            "project_material_notes": material_notes,
        },
    )
    db.update_run(run["id"], status="running")
    output_dir = run_dir(run["id"]) / "glossary"
    output_dir.mkdir(parents=True, exist_ok=True)
    input_path = Path(artifact["path"])
    detail_output = output_dir / f"{input_path.stem}_glossary_details.xlsx"
    final_output = output_dir / f"{input_path.stem}_ID_CN_EN_EN2.xlsx"
    brief_output = output_dir / "project_brief.md"
    prompt_output = output_dir / "translation_prompt.txt"
    args = [
        sys.executable,
        str(GLOSSARY_ROOT / "scripts" / "extract_glossary.py"),
        str(input_path),
        "--id-column",
        request.id_column,
        "--source-column",
        request.source_column,
        "--target-column",
        request.target_column,
        "--output",
        str(detail_output),
        "--final-output",
        str(final_output),
        "--project-name",
        request.project_name or project["name"],
        "--project-brief-output",
        str(brief_output),
        "--translation-prompt-output",
        str(prompt_output),
        "--curated-rules",
        str(project_dir(project_id) / "glossary" / "curated_terms.json"),
        "--observations-store",
        str(project_dir(project_id) / "glossary" / "observed_terms.json"),
    ]
    if request.sheet:
        args.extend(["--sheet", request.sheet])
    if request.source_only:
        args.append("--source-only")
    if request.include_empty_final_terms:
        args.append("--include-empty-final-terms")
    for material_artifact_id in material_artifact_ids:
        material_artifact = db.get_artifact(material_artifact_id)
        args.extend(["--project-material", material_artifact["path"]])
    for note in [*project_notes, *material_notes]:
        args.extend(["--project-note", note])
    try:
        proc = run_subprocess(args, GLOSSARY_ROOT, run["id"])
        parsed = parse_key_output(proc.stdout)
        artifacts = [
            db.add_artifact(project_id, "Glossary details", detail_output, "glossary_detail", run_id=run["id"]),
            db.add_artifact(project_id, "ID CN EN EN2 glossary", final_output, "glossary_final", run_id=run["id"]),
            db.add_artifact(project_id, "Project brief", brief_output, "project_brief", run_id=run["id"], mime="text/markdown"),
            db.add_artifact(project_id, "Translation prompt", prompt_output, "translation_prompt", run_id=run["id"], mime="text/plain"),
        ]
        backfill = backfill_project_glossary_from_final(project_id, final_output, run["id"])
        if prompt_output.exists():
            prompt = prompt_output.read_text(encoding="utf-8")
            db.update_project(project_id, {"prompt_text": prompt})
        db.update_run(run["id"], status="passed", metadata={"output": parsed, "glossary_backfill": backfill})
        return {"run": db.get_run(run["id"]), "artifacts": artifacts, "output": parsed, "glossary_backfill": backfill}
    except Exception as exc:
        db.add_event(run["id"], str(exc), level="error")
        db.update_run(run["id"], status="failed", metadata={"error": str(exc)})
        raise


def backfill_project_glossary_from_final(project_id: str, final_output: Path, run_id: str | None = None) -> dict[str, Any]:
    """Apply generated glossary rows to the project term table without overwriting curated decisions."""
    if not final_output.exists():
        result = {"candidates": 0, "inserted": 0, "updated": 0, "skipped_existing": 0, "skipped_empty": 0}
        if run_id:
            db.add_event(run_id, "高频词补充跳过：未找到生成的 ID/CN/EN/EN2 术语文件。", level="warn")
        return result
    rows, _columns = _read_glossary_rows(final_output, limit=None)
    existing = {str(term.get("source", "")).strip(): term for term in db.list_glossary_terms(project_id) if str(term.get("source", "")).strip()}
    result = {"candidates": len(rows), "inserted": 0, "updated": 0, "skipped_existing": 0, "skipped_empty": 0}
    if run_id:
        db.add_event(
            run_id,
            "高频词补充策略：读取生成的 ID/CN/EN/EN2 候选；项目中不存在的候选会新增，"
            "EN/EN2 为空时作为待补译词条；已有词条只补空白 EN/EN2，不覆盖人工译名或已导入译名。",
        )
    for row in rows:
        source = str(row.get("source") or "").strip()
        target = str(row.get("target") or "").strip()
        target_alt = str(row.get("target_alt") or "").strip()
        if not source:
            result["skipped_empty"] += 1
            continue
        current = existing.get(source)
        if current:
            updates: dict[str, Any] = {}
            if target and not str(current.get("target") or "").strip():
                updates["target"] = target
            if target_alt and not str(current.get("target_alt") or "").strip():
                updates["target_alt"] = target_alt
            if updates:
                updates["note"] = str(current.get("note") or "高频词扫描补充").strip() or "高频词扫描补充"
                db.update_glossary_term(current["id"], updates)
                current.update(updates)
                result["updated"] += 1
            else:
                result["skipped_existing"] += 1
            continue
        created = db.insert_glossary_term(
            project_id,
            {
                "term_key": row.get("term_key", ""),
                "source": source,
                "target": target,
                "target_alt": target_alt,
                "category": row.get("category", "") or "generated",
                "note": row.get("note", "") or ("高频词扫描补充" if target or target_alt else "高频词扫描候选，待补译"),
                "source_type": "generated",
                "confirmed": False,
            },
        )
        existing[source] = created
        result["inserted"] += 1
    if run_id:
        db.add_event(
            run_id,
            "高频词补充结果："
            f"候选 {result['candidates']}，新增 {result['inserted']}，补全 {result['updated']}，"
            f"保留已有 {result['skipped_existing']}，跳过空项 {result['skipped_empty']}。",
        )
    return result


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def preview_glossary_import(project_id: str, request: Any, import_all: bool = False) -> dict[str, Any]:
    project = db.get_project(project_id)
    _ = project
    artifact = db.get_artifact(request.artifact_id)
    path = Path(artifact["path"])
    rows, columns = _read_glossary_rows(
        path,
        sheet=getattr(request, "sheet", None),
        term_key_column=getattr(request, "term_key_column", None),
        source_column=getattr(request, "source_column", None),
        target_column=getattr(request, "target_column", None),
        target_alt_column=getattr(request, "target_alt_column", None),
        category_column=getattr(request, "category_column", None),
        note_column=getattr(request, "note_column", None),
        limit=None if import_all else int(getattr(request, "limit", 100) or 100),
    )
    return {"artifact": artifact, "columns": columns, "rows": rows, "total_rows": len(rows)}


def import_glossary(project_id: str, request: Any) -> dict[str, Any]:
    preview = preview_glossary_import(project_id, request, import_all=True)
    imported = []
    for row in preview["rows"]:
        if not row.get("source"):
            continue
        imported.append(
            db.insert_glossary_term(
                project_id,
                {
                    "term_key": row.get("term_key", ""),
                    "source": row.get("source", ""),
                    "target": row.get("target", ""),
                    "target_alt": row.get("target_alt", ""),
                    "category": row.get("category", "imported"),
                    "note": row.get("note", ""),
                    "source_type": "imported",
                    "confirmed": True,
                },
            )
        )
    return {"imported_count": len(imported), "terms": imported, "preview": preview}


def export_glossary(project_id: str, fmt: str) -> dict[str, Any] | Path:
    terms = db.list_glossary_terms(project_id)
    if fmt == "json":
        return {
            "project_id": project_id,
            "terms": [dict(zip(("term_key", "source", "target", "target_alt", "category", "note"), _glossary_export_row(term))) for term in terms],
        }
    output_dir = project_dir(project_id) / "glossary" / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)
    columns = ["ID", "CN", "EN", "EN2", "分类", "备注"]
    if fmt == "csv":
        path = output_dir / "project_glossary.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(columns)
            for term in terms:
                writer.writerow(_glossary_export_row(term))
        return path
    path = output_dir / "project_glossary.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Glossary"
    ws.append(columns)
    for term in terms:
        ws.append(_glossary_export_row(term))
    wb.save(path)
    wb.close()
    return path


def _glossary_export_row(term: dict[str, Any]) -> list[Any]:
    return [
        term.get("term_key", ""),
        term.get("source", ""),
        term.get("target", ""),
        term.get("target_alt", ""),
        term.get("category", ""),
        term.get("note", ""),
    ]


def build_delivery_package(project_id: str) -> dict[str, Any]:
    project = db.get_project(project_id)
    safe_name = _safe_delivery_name(project["name"])
    output_dir = project_dir(project_id) / "delivery"
    output_dir.mkdir(parents=True, exist_ok=True)
    for existing in output_dir.iterdir():
        if existing.is_file():
            existing.unlink()

    files: list[dict[str, str]] = []
    translated_path = output_dir / f"{safe_name}_translated.xlsx"
    translated_source = _latest_artifact(project_id, role="translation_workbook", kind="qa_final_workbook")
    if translated_source and Path(translated_source["path"]).exists():
        shutil.copy2(translated_source["path"], translated_path)
    else:
        raise ValueError("QA 未通过，暂无最终交付 workbook")
    files.append(_delivery_file("translated", translated_path))

    changes_path = output_dir / f"{safe_name}_qa_changes.xlsx"
    qa_changes_source = _latest_artifact(project_id, kind="qa_changes")
    if qa_changes_source and Path(qa_changes_source["path"]).exists():
        shutil.copy2(qa_changes_source["path"], changes_path)
    else:
        write_qa_changes_report(output_dir, []).replace(changes_path)
    files.append(_delivery_file("qa_changes", changes_path))
    return {"project_id": project_id, "project_name": project["name"], "files": files}


def _safe_delivery_name(name: str) -> str:
    cleaned = "".join(ch for ch in name if ch not in '<>:"/\\|?*').strip()
    return cleaned or "project"


def _delivery_file(kind: str, path: Path) -> dict[str, str]:
    return {"kind": kind, "filename": path.name, "path": str(path)}


def _write_empty_workbook(path: Path, headers: list[str], note: str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Delivery"
    ws.append(headers)
    ws.append(["", note, ""])
    wb.save(path)
    wb.close()


def _latest_artifact(project_id: str, role: str | None = None, kind: str | None = None) -> dict[str, Any] | None:
    artifacts = db.list_artifacts(project_id=project_id, role=role)
    if kind:
        artifacts = [artifact for artifact in artifacts if artifact["kind"] == kind]
    return artifacts[0] if artifacts else None


def _read_glossary_rows(
    path: Path,
    sheet: str | None = None,
    term_key_column: str | None = None,
    source_column: str | None = None,
    target_column: str | None = None,
    target_alt_column: str | None = None,
    category_column: str | None = None,
    note_column: str | None = None,
    limit: int | None = 100,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        headers = [str(cell.value or "").strip() for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        normalized = {header.lower(): index for index, header in enumerate(headers) if header}
        term_key_idx = _column_index(normalized, term_key_column, ["id", "key", "编号", "序号"], required=False)
        source_idx = _column_index(normalized, source_column, ["source", "original", "cn", "zh", "chinese", "term", "原文", "中文", "术语"])
        target_idx = _column_index(normalized, target_column, ["target", "translation", "en", "english", "译文", "英文"])
        target_alt_idx = _column_index(normalized, target_alt_column, ["en2", "en 2", "alt", "alternate", "variant", "备用英文"], required=False)
        category_idx = _column_index(normalized, category_column, ["category", "type", "类别", "类型"], required=False)
        note_idx = _column_index(normalized, note_column, ["note", "notes", "comment", "备注"], required=False)
        rows = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if limit is not None and len(rows) >= limit:
                break
            source = _value_at(row, source_idx)
            target = _value_at(row, target_idx)
            if not source and not target:
                continue
            rows.append(
                {
                    "term_key": _value_at(row, term_key_idx) if term_key_idx is not None else "",
                    "source": source,
                    "target": target,
                    "target_alt": _value_at(row, target_alt_idx) if target_alt_idx is not None else "",
                    "category": _value_at(row, category_idx) if category_idx is not None else "imported",
                    "note": _value_at(row, note_idx) if note_idx is not None else "",
                }
            )
        return rows, {
            "term_key": headers[term_key_idx] if term_key_idx is not None else "",
            "source": headers[source_idx],
            "target": headers[target_idx],
            "target_alt": headers[target_alt_idx] if target_alt_idx is not None else "",
            "category": headers[category_idx] if category_idx is not None else "",
            "note": headers[note_idx] if note_idx is not None else "",
        }
    finally:
        wb.close()


def _column_index(normalized_headers: dict[str, int], explicit: str | None, candidates: list[str], required: bool = True) -> int | None:
    if explicit:
        hit = normalized_headers.get(explicit.strip().lower())
        if hit is not None:
            return hit
        if required:
            raise KeyError(f"column not found: {explicit}")
    for candidate in candidates:
        hit = normalized_headers.get(candidate.lower())
        if hit is not None:
            return hit
    if required:
        raise KeyError(f"none of columns found: {', '.join(candidates)}")
    return None


def _value_at(row: tuple[Any, ...], index: int | None) -> str:
    if index is None or index < 0 or index >= len(row):
        return ""
    value = row[index]
    return "" if value is None else str(value).strip()


def run_project_harness_qa(final_workbook: Path, harness: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    if not final_workbook.exists():
        return {
            "source": "project_harness",
            "passed": False,
            "hard_errors": 1,
            "soft_warnings": 0,
            "issues": [{"severity": "hard", "message": "final workbook missing", "rule_source": "project_harness"}],
        }

    forbidden = [str(item).strip() for item in harness.get("forbidden_translations", []) if str(item).strip()]
    fixed_terms = [item for item in harness.get("fixed_terms", []) if isinstance(item, dict)]
    hard_rules = [item for item in harness.get("hard_rules", []) if isinstance(item, dict) and item.get("enabled", True)]

    wb = load_workbook(final_workbook, data_only=False)
    try:
        for ws in wb.worksheets:
            headers = _header_map(ws)
            source_col = _first_col(headers, ["cn", "source", "original", "原文", "中文"])
            target_col = _first_col(headers, ["en", "translation", "target", "译文", "英文"])
            if target_col is None:
                continue
            for row_index in range(2, ws.max_row + 1):
                source = _cell_text(ws.cell(row_index, source_col).value) if source_col else ""
                target = _cell_text(ws.cell(row_index, target_col).value)
                if not target:
                    continue
                for phrase in forbidden:
                    if phrase in target:
                        issues.append(
                            _project_issue(
                                ws.title,
                                row_index,
                                "forbidden_translation",
                                f"Translation contains forbidden phrase: {phrase}",
                                target,
                            )
                        )
                for term in fixed_terms:
                    source_term = str(term.get("source", "")).strip()
                    target_term = str(term.get("target", "")).strip()
                    if source_term and target_term and source_term in source and target_term not in target:
                        issues.append(
                            _project_issue(
                                ws.title,
                                row_index,
                                "fixed_term_missing",
                                f"Source term '{source_term}' must use '{target_term}'",
                                target,
                            )
                        )
                for rule in hard_rules:
                    pattern = str(rule.get("pattern", "")).strip()
                    if not pattern:
                        continue
                    try:
                        matched = re.search(pattern, target) is not None
                    except re.error as exc:
                        issues.append(
                            _project_issue(
                                ws.title,
                                row_index,
                                "invalid_project_rule",
                                f"Invalid project hard-rule pattern '{pattern}': {exc}",
                                target,
                                severity="soft",
                            )
                        )
                        continue
                    if matched:
                        message = str(rule.get("description") or rule.get("label") or f"Project rule matched: {pattern}")
                        issues.append(_project_issue(ws.title, row_index, "project_hard_rule", message, target))
    finally:
        wb.close()

    hard_errors = len([issue for issue in issues if issue["severity"] == "hard"])
    soft_warnings = len([issue for issue in issues if issue["severity"] == "soft"])
    return {
        "source": "project_harness",
        "passed": hard_errors == 0,
        "hard_errors": hard_errors,
        "soft_warnings": soft_warnings,
        "issues": issues[:100],
        "active_overlay": _harness_summary(harness),
    }


def list_improvements(project_id: str) -> list[dict[str, Any]]:
    path = project_dir(project_id) / "profile" / "improvement_suggestions.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def create_improvement_review(run_id: str) -> dict[str, Any]:
    run = db.get_run(run_id)
    project_id = run["project_id"]
    metadata = run.get("metadata", {})
    suggestions = list_improvements(project_id)
    quality = metadata.get("quality", {})
    project_quality = metadata.get("project_harness_quality", {})
    if project_quality.get("hard_errors"):
        suggestions.append(
            _improvement_item(
                "project_harness",
                run_id,
                "Review project-specific hard rules and manual fixes",
                "Project harness QA produced hard errors; update this project's harness only after human review.",
            )
        )
    if quality and not quality.get("passed", True):
        suggestions.append(
            _improvement_item(
                "studio_integration",
                run_id,
                "Review reusable QA adapter coverage",
                "Global quality gate failed; inspect whether Studio needs better reporting or retry controls.",
            )
        )
    suggestions.append(
        _improvement_item(
            "upstream_backfeed",
            run_id,
            "Prepare upstream backfeed candidate",
            "If this run exposed a reusable gap, create a human-reviewed issue or PR against the source workflow repo.",
        )
    )
    path = project_dir(project_id) / "profile" / "improvement_suggestions.json"
    path.write_text(json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"project_id": project_id, "run_id": run_id, "suggestions": suggestions}


def list_quality_issues(run_id: str) -> dict[str, Any]:
    run = db.get_run(run_id)
    metadata = run.get("metadata", {})
    summary = metadata.get("quality_summary", {})
    issues: list[dict[str, Any]] = []
    for source_key, payload in (
        ("global_harness", metadata.get("quality") or summary.get("global_harness_quality") or {}),
        ("project_harness", metadata.get("project_harness_quality") or summary.get("project_harness_quality") or {}),
        ("semantic_qa", metadata.get("semantic_qa") or summary.get("semantic_qa") or {}),
    ):
        issues.extend(_normalize_quality_issues(source_key, payload))
    hard_errors = len([issue for issue in issues if issue["severity"] == "hard"])
    return {
        "run_id": run_id,
        "project_id": run["project_id"],
        "status": run["status"],
        "hard_errors": hard_errors,
        "issues": issues,
    }


def apply_manual_fixes(run_id: str, request: Any) -> dict[str, Any]:
    run = db.get_run(run_id)
    project_id = run["project_id"]
    fixes = [fix.model_dump() if hasattr(fix, "model_dump") else dict(fix) for fix in getattr(request, "fixes", [])]
    if not fixes:
        raise ValueError("manual fixes are required")

    source_artifact = _workbook_artifact_for_quality_run(run)
    source_path = Path(source_artifact["path"])
    if not source_path.exists():
        raise FileNotFoundError(str(source_path))

    output_dir = run_dir(run_id) / "manual_fixes"
    output_dir.mkdir(parents=True, exist_ok=True)
    fixed_path = output_dir / f"{source_path.stem}_manual_fixed.xlsx"
    shutil.copy2(source_path, fixed_path)

    applied = _apply_workbook_fixes(fixed_path, fixes, run_id)
    fixed_artifact = db.add_artifact(
        project_id,
        "Manual fixed workbook",
        fixed_path,
        "manual_fixed_workbook",
        run_id=run_id,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        origin="manual",
        metadata={"source_run_id": run_id, "source_artifact_id": source_artifact["id"], "manual_fix_count": len(applied)},
    )
    harness = read_project_harness(project_id)
    write_project_harness(
        project_id,
        {
            "manual_fixes": [*harness.get("manual_fixes", []), *applied],
            "qa_summary": {
                **harness.get("qa_summary", {}),
                "last_manual_fix_run": run_id,
                "last_manual_fix_artifact": fixed_artifact["id"],
            },
        },
    )
    _append_improvement_items(
        project_id,
        [
            _improvement_item(
                "project_harness",
                run_id,
                "Review manual fixes for project harness reuse",
                "Manual QA fixes were applied; review whether they should become project-specific rules, fixed terms, or reference examples.",
            )
        ],
    )

    result: dict[str, Any] = {
        "source_run": run,
        "fixed_artifact": fixed_artifact,
        "manual_fixes": applied,
        "qa_result": None,
    }
    if getattr(request, "rerun_qa", True):
        qa_run = db.insert_run(
            project_id,
            kind="qa",
            language=run.get("language", "en"),
            metadata={
                "input_artifact_id": fixed_artifact["id"],
                "manual_fix_source_run_id": run_id,
                "manual_fix_source_artifact_id": source_artifact["id"],
                "manual_fix_count": len(applied),
                "manual_fixes": applied,
            },
        )
        result["qa_result"] = run_qa_sync(qa_run["id"])
    return result


def create_semantic_qa_context(run_id: str) -> dict[str, Any]:
    run = db.get_run(run_id)
    project = db.get_project(run["project_id"])
    output_dir = run_dir(run_id) / "semantic_qa"
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "needs_model_review",
        "message": "Semantic QA context is prepared; model review is not auto-marked as passed.",
        "run_id": run_id,
        "project_id": project["id"],
        "sources": {
            "global_harness": GLOBAL_HARNESS_CONTRACT,
            "project_harness": read_project_harness(project["id"]),
        },
        "run_quality": {
            "global": run.get("metadata", {}).get("quality", {}),
            "project_harness": run.get("metadata", {}).get("project_harness_quality", {}),
        },
    }
    path = output_dir / "semantic_qa_context.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    artifact = db.add_artifact(project["id"], "Semantic QA context", path, "semantic_qa_context", run_id=run_id, mime="application/json")
    return {"run": db.get_run(run_id), "artifact": artifact, "semantic_qa": report}


def run_qa_sync(run_id: str) -> dict[str, Any]:
    run = db.get_run(run_id)
    project = db.get_project(run["project_id"])
    metadata = run.get("metadata", {})
    input_artifact_id = metadata.get("input_artifact_id")
    if not input_artifact_id:
        raise KeyError("input_artifact_id")
    workbook_artifact = db.get_artifact(input_artifact_id)
    workbook_path = Path(workbook_artifact["path"])
    db.update_run(run_id, status="running")

    output_dir = run_dir(run_id) / "qa"
    output_dir.mkdir(parents=True, exist_ok=True)
    glossary_snapshot = create_project_glossary_snapshot(project["id"], run_id, output_dir / "snapshots")
    snapshots = create_prompt_and_harness_snapshots(project["id"], run_id, output_dir / "snapshots")
    qa_result = run_localization_qa(
        project=project,
        run_id=run_id,
        workbook_path=workbook_path,
        output_dir=output_dir,
        glossary_snapshot=glossary_snapshot,
        harness_snapshot=snapshots["harness_snapshot"],
        workbook_artifact=workbook_artifact,
        run_metadata=metadata,
        manual_fixes=metadata.get("manual_fixes") or [],
    )
    input_artifacts = {
        "translation_workbook": workbook_artifact["id"],
        "glossary_snapshot": glossary_snapshot["id"],
        "prompt_snapshot": snapshots["prompt_artifact"]["id"],
        "harness_snapshot": snapshots["harness_artifact"]["id"],
    }
    if qa_result.get("qa_final_artifact"):
        input_artifacts["qa_final_workbook"] = qa_result["qa_final_artifact"]["id"]
    status = "passed" if qa_result["quality_summary"]["passed"] else "failed"
    db.update_run(
        run_id,
        status=status,
        metadata={
            **metadata,
            "task_origin": metadata.get("task_origin") or "direct_import",
            "input_artifacts": input_artifacts,
            "quality": qa_result["quality"],
            "project_harness_quality": qa_result["project_harness_quality"],
            "semantic_qa": qa_result["semantic_qa"],
            "quality_summary": qa_result["quality_summary"],
        },
    )
    return {"run": db.get_run(run_id), "artifacts": qa_result["artifacts"], "quality_summary": qa_result["quality_summary"]}


def run_localization_qa(
    project: dict[str, Any],
    run_id: str,
    workbook_path: Path,
    output_dir: Path,
    glossary_snapshot: dict[str, Any],
    harness_snapshot: dict[str, Any],
    workbook_artifact: dict[str, Any] | None = None,
    run_metadata: dict[str, Any] | None = None,
    manual_fixes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    machine_dir = output_dir / "machine_review"
    machine_dir.mkdir(parents=True, exist_ok=True)
    review_args = [
        sys.executable,
        str(LOCALIZATION_ROOT / "process_language.py"),
        "--input",
        str(workbook_path),
        "--lang",
        "en",
        "--output-dir",
        str(machine_dir),
        "--auto-fix",
        "--term-base",
        glossary_snapshot["path"],
    ]
    run_subprocess(review_args, LOCALIZATION_ROOT, run_id)
    qa_workbook = machine_dir / "result_en.xlsx"
    qa_report = machine_dir / "report_en.xlsx"
    _normalize_review_workbook_sheet_names(qa_workbook, workbook_path)
    quality_args = [
        sys.executable,
        str(LOCALIZATION_ROOT / "scripts" / "run_quality_harness.py"),
        str(LOCALIZATION_ROOT / "fixtures" / "quality_regression.json"),
        "--workbook",
        str(qa_workbook),
        "--term-base",
        glossary_snapshot["path"],
        "--json",
    ]
    quality = _run_quality_json(quality_args, run_id)
    project_harness_quality = run_project_harness_qa(qa_workbook, harness_snapshot["project_harness"])
    semantic_qa = run_semantic_qa_report(run_id, project["id"], qa_workbook, quality, project_harness_quality)
    hard_errors = _hard_error_count(quality) + int(project_harness_quality.get("hard_errors", 0)) + int(semantic_qa.get("hard_errors", 0))
    passed = hard_errors == 0
    summary = {
        "version": 1,
        "run_id": run_id,
        "project_id": project["id"],
        "passed": passed,
        "hard_errors": hard_errors,
        "sources": {
            "translation_workbook": (workbook_artifact or {}).get("id", ""),
            "qa_workbook": str(qa_workbook),
            "glossary_snapshot": glossary_snapshot["id"],
            "global_harness": GLOBAL_HARNESS_CONTRACT,
            "project_harness": "project_harness_snapshot.json",
            "semantic_qa": semantic_qa.get("status", ""),
        },
        "global_harness_quality": quality,
        "project_harness_quality": project_harness_quality,
        "semantic_qa": semantic_qa,
    }
    metadata = run_metadata or {}
    if metadata.get("manual_fix_source_run_id"):
        summary["sources"]["manual_fix_source_run"] = metadata["manual_fix_source_run_id"]
    summary_path = output_dir / "quality_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    auto_fixes = _collect_workbook_translation_changes(workbook_path, qa_workbook)
    changes_path = write_qa_changes_report(output_dir, manual_fixes or [], auto_fixes)
    artifacts = [
        db.add_artifact(
            project["id"],
            "QA reviewed workbook",
            qa_workbook,
            "qa_result",
            run_id=run_id,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        db.add_artifact(
            project["id"],
            "QA report",
            qa_report,
            "qa_report",
            run_id=run_id,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        db.add_artifact(project["id"], "Quality summary", summary_path, "quality_summary", run_id=run_id, mime="application/json"),
        db.add_artifact(
            project["id"],
            "QA changes",
            changes_path,
            "qa_changes",
            run_id=run_id,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    ]
    qa_final_artifact = None
    if passed:
        qa_final_artifact = db.add_artifact(
            project["id"],
            "QA final workbook",
            qa_workbook,
            "qa_final_workbook",
            run_id=run_id,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            origin="generated",
            metadata={"language": "en", "source_workbook": str(workbook_path), "glossary_snapshot": glossary_snapshot["id"]},
        )
        artifacts.append(qa_final_artifact)
    return {
        "artifacts": artifacts,
        "qa_final_artifact": qa_final_artifact,
        "quality": quality,
        "project_harness_quality": project_harness_quality,
        "semantic_qa": semantic_qa,
        "quality_summary": summary,
        "qa_workbook": qa_workbook,
    }


def write_qa_changes_report(output_dir: Path, manual_fixes: list[dict[str, Any]], auto_fixes: list[dict[str, Any]] | None = None) -> Path:
    path = output_dir / "qa_changes.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "QA Changes"
    ws.append(["工作表", "行号", "问题ID", "修改前", "修改后", "规则来源", "备注"])
    if manual_fixes:
        for fix in manual_fixes:
            ws.append(
                [
                    fix.get("sheet", ""),
                    fix.get("row", ""),
                    fix.get("issue_id", ""),
                    fix.get("previous_translation", ""),
                    fix.get("translation", ""),
                    "manual_fix",
                    fix.get("note", ""),
                ]
            )
    for fix in auto_fixes or []:
        ws.append(
            [
                fix.get("sheet", ""),
                fix.get("row", ""),
                fix.get("issue_id", "auto_fix"),
                fix.get("previous_translation", ""),
                fix.get("translation", ""),
                "localization_auto_fix",
                fix.get("note", ""),
            ]
        )
    if not manual_fixes and not auto_fixes:
        ws.append(["", "", "", "", "", "qa", "未应用修改"])
    wb.save(path)
    wb.close()
    return path


def _run_quality_json(args: list[str], run_id: str) -> dict[str, Any]:
    proc = run_subprocess_allow_failure(args, LOCALIZATION_ROOT, run_id)
    if not proc.stdout.strip():
        raise RuntimeError(f"quality harness returned no JSON: {proc.stderr}")
    return json.loads(proc.stdout)


def _hard_error_count(quality: dict[str, Any]) -> int:
    if quality.get("passed"):
        return 0
    hard_issues = [
        issue
        for issue in quality.get("issues", [])
        if str(issue.get("severity", "hard")).lower() not in {"warning", "soft", "info"}
    ]
    issue_count = len(hard_issues) + len(quality.get("failures", []))
    if issue_count:
        return issue_count
    return 1 if not quality.get("issues") and not quality.get("failures") else 0


def run_semantic_qa_report(
    run_id: str,
    project_id: str,
    workbook_path: Path,
    quality: dict[str, Any],
    project_quality: dict[str, Any],
) -> dict[str, Any]:
    settings = load_settings()
    provider = str(settings.get("provider") or "mock")
    model = str(settings.get("model") or "")
    issue_context = {
        "global_issue_count": len(quality.get("issues", [])),
        "project_harness_issue_count": len(project_quality.get("issues", [])),
        "sample_issues": (quality.get("issues", []) or [])[:20],
        "project_issues": (project_quality.get("issues", []) or [])[:20],
    }
    base = {
        "source": "semantic_qa",
        "provider": provider,
        "model": model,
        "prompt_context": {"run_id": run_id, "project_id": project_id, **issue_context},
        "issues": [],
        "soft_warnings": 0,
    }
    if provider == "mock" or not settings.get("api_key"):
        return {**base, "status": "skipped_no_key", "passed": True, "hard_errors": 0}

    prompt = (
        "You are doing semantic QA for a game localization workbook. "
        "Review the machine QA context and return strict JSON only: "
        "{\"passed\": boolean, \"issues\": [{\"severity\":\"hard|soft\", \"message\":\"...\", \"sheet\":\"\", \"row\":0}]}.\n"
        f"Workbook: {workbook_path.name}\n"
        f"Context:\n{json.dumps(issue_context, ensure_ascii=False)}"
    )
    try:
        text = _call_semantic_provider(settings, prompt)
        payload = _parse_semantic_qa_payload(text)
        issues = payload.get("issues", []) if isinstance(payload.get("issues"), list) else []
        hard_errors = len([issue for issue in issues if str(issue.get("severity", "hard")).lower() == "hard"])
        return {
            **base,
            "status": "model_reviewed",
            "passed": bool(payload.get("passed", hard_errors == 0)) and hard_errors == 0,
            "hard_errors": hard_errors,
            "soft_warnings": len([issue for issue in issues if str(issue.get("severity", "")).lower() == "soft"]),
            "issues": issues,
        }
    except Exception as exc:
        return {
            **base,
            "status": "provider_error",
            "passed": False,
            "hard_errors": 1,
            "issues": [{"severity": "hard", "message": f"Semantic QA provider failed: {exc}", "sheet": "", "row": 0}],
        }


def _call_semantic_provider(settings: dict[str, Any], prompt: str) -> str:
    import httpx

    provider = str(settings.get("provider") or "openai")
    base_url = str(settings.get("base_url") or ("https://api.anthropic.com" if provider == "anthropic" else "https://api.openai.com")).rstrip("/")
    api_key = str(settings.get("api_key") or "")
    model = str(settings.get("model") or ("claude-opus-4-7" if provider == "anthropic" else "gpt-5.5"))
    if provider == "anthropic":
        response = httpx.post(
            f"{base_url}/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            json={"model": model, "max_tokens": 4096, "system": "Return strict JSON only.", "messages": [{"role": "user", "content": prompt}]},
            timeout=120,
        )
        response.raise_for_status()
        chunks = [str(item.get("text", "")) for item in response.json().get("content", []) if item.get("type") == "text"]
        return "\n".join(chunks)
    if str(settings.get("protocol") or "chat-completions") == "responses":
        response = httpx.post(
            f"{base_url}/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "input": prompt, "reasoning": {"effort": settings.get("reasoning_effort") or "medium"}},
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
        return str(payload.get("output_text") or "")
    response = httpx.post(
        f"{base_url}/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "temperature": 0.1, "messages": [{"role": "system", "content": "Return strict JSON only."}, {"role": "user", "content": prompt}]},
        timeout=120,
    )
    response.raise_for_status()
    return str(response.json()["choices"][0]["message"]["content"])


def _parse_semantic_qa_payload(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def _collect_workbook_translation_changes(before_path: Path, after_path: Path) -> list[dict[str, Any]]:
    if not before_path.exists() or not after_path.exists():
        return []
    before_wb = load_workbook(before_path, read_only=True, data_only=True)
    after_wb = load_workbook(after_path, read_only=True, data_only=True)
    changes: list[dict[str, Any]] = []
    try:
        before_ws = before_wb[before_wb.sheetnames[0]]
        after_ws = after_wb[before_ws.title] if before_ws.title in after_wb.sheetnames else after_wb[after_wb.sheetnames[0]]
        before_headers = _header_map(before_ws)
        after_headers = _header_map(after_ws)
        before_id_col = _first_col(before_headers, ["id", "key", "编号", "序号"])
        after_id_col = _first_col(after_headers, ["id", "key", "编号", "序号"])
        before_target_col = _first_col(before_headers, ["en", "translation", "target", "译文", "英文"])
        after_target_col = _first_col(after_headers, ["en", "translation", "target", "译文", "英文"])
        if before_id_col is None or after_id_col is None or before_target_col is None or after_target_col is None:
            return []
        after_by_id: dict[str, tuple[int, str]] = {}
        for row_index, row in enumerate(after_ws.iter_rows(min_row=2, values_only=True), start=2):
            row_id = _row_cell(row, after_id_col)
            if row_id:
                after_by_id[row_id] = (row_index, _row_cell(row, after_target_col))
        for row_index, row in enumerate(before_ws.iter_rows(min_row=2, values_only=True), start=2):
            row_id = _row_cell(row, before_id_col)
            if not row_id or row_id not in after_by_id:
                continue
            after_row, after_text = after_by_id[row_id]
            before_text = _row_cell(row, before_target_col)
            if before_text != after_text:
                changes.append(
                    {
                        "sheet": after_ws.title,
                        "row": after_row,
                        "issue_id": "auto_fix",
                        "previous_translation": before_text,
                        "translation": after_text,
                        "note": f"localization workflow auto-fix for ID {row_id}",
                    }
                )
    finally:
        before_wb.close()
        after_wb.close()
    return changes


def _normalize_review_workbook_sheet_names(review_path: Path, source_path: Path) -> None:
    if not review_path.exists() or not source_path.exists():
        return
    source_wb = load_workbook(source_path, read_only=True, data_only=True)
    review_wb = load_workbook(review_path)
    try:
        source_title = source_wb.sheetnames[0] if source_wb.sheetnames else ""
        if source_title and review_wb.sheetnames:
            first = review_wb[review_wb.sheetnames[0]]
            if first.title != source_title and source_title not in review_wb.sheetnames:
                first.title = source_title
                review_wb.save(review_path)
    finally:
        source_wb.close()
        review_wb.close()


def _row_cell(row: tuple[Any, ...], column: int) -> str:
    if column < 1 or column > len(row):
        return ""
    value = row[column - 1]
    return "" if value is None else str(value).strip()


def _normalize_quality_issues(source_key: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, issue in enumerate(payload.get("issues", []) or []):
        severity = str(issue.get("severity") or "hard").lower()
        if severity in {"warning", "soft", "info"}:
            severity = "soft" if severity != "info" else "info"
        else:
            severity = "hard"
        rows.append(
            {
                "id": str(issue.get("id") or f"{source_key}:{index}:{issue.get('sheet', '')}:{issue.get('row', '')}:{issue.get('check_type', '')}"),
                "source": source_key,
                "rule_source": issue.get("rule_source") or issue.get("source") or source_key,
                "severity": severity,
                "sheet": issue.get("sheet") or "",
                "row": int(issue.get("row") or 0),
                "check_type": issue.get("check_type") or issue.get("type") or issue.get("code") or "quality_issue",
                "message": issue.get("message") or issue.get("detail") or "",
                "current_translation": issue.get("translation") or issue.get("target") or issue.get("actual") or "",
            }
        )
    for index, failure in enumerate(payload.get("failures", []) or []):
        rows.append(
            {
                "id": str(failure.get("id") or f"{source_key}:failure:{index}"),
                "source": source_key,
                "rule_source": source_key,
                "severity": "hard",
                "sheet": failure.get("sheet") or "",
                "row": int(failure.get("row") or 0),
                "check_type": "fixture_failure",
                "message": failure.get("message") or f"Fixture failure: {failure.get('id', index)}",
                "current_translation": failure.get("actual") or "",
            }
        )
    return rows


def _workbook_artifact_for_quality_run(run: dict[str, Any]) -> dict[str, Any]:
    metadata = run.get("metadata", {})
    input_artifact_id = metadata.get("input_artifacts", {}).get("translation_workbook") or metadata.get("input_artifact_id")
    if input_artifact_id:
        artifact = db.get_artifact(input_artifact_id)
        if artifact["role"] in {"translation_workbook", "translation_draft"}:
            return artifact
    artifacts = db.list_artifacts(run_id=run["id"], role="translation_workbook")
    if artifacts:
        return artifacts[0]
    raise KeyError("translation workbook artifact not found")


def _apply_workbook_fixes(path: Path, fixes: list[dict[str, Any]], source_run_id: str) -> list[dict[str, Any]]:
    wb = load_workbook(path)
    applied: list[dict[str, Any]] = []
    try:
        for fix in fixes:
            row_index = int(fix.get("row") or 0)
            if row_index < 2:
                raise ValueError(f"invalid workbook row: {row_index}")
            sheet_name = str(fix.get("sheet") or wb.sheetnames[0]).strip()
            if sheet_name not in wb.sheetnames:
                raise KeyError(f"sheet not found: {sheet_name}")
            ws = wb[sheet_name]
            target_col = _first_col(_header_map(ws), ["en", "translation", "target", "译文", "英文"])
            if target_col is None:
                raise KeyError(f"target column not found in sheet: {sheet_name}")
            cell = ws.cell(row_index, target_col)
            previous = _cell_text(cell.value)
            translation = str(fix.get("translation") or "").strip()
            cell.value = translation
            applied.append(
                {
                    "id": db.new_id("fix"),
                    "source_run_id": source_run_id,
                    "issue_id": fix.get("issue_id") or "",
                    "sheet": sheet_name,
                    "row": row_index,
                    "column": target_col,
                    "previous_translation": previous,
                    "translation": translation,
                    "note": str(fix.get("note") or "").strip(),
                    "applied_at": db.now_iso(),
                }
            )
        wb.save(path)
    finally:
        wb.close()
    return applied


def _append_improvement_items(project_id: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    suggestions = list_improvements(project_id)
    suggestions.extend(items)
    path = project_dir(project_id) / "profile" / "improvement_suggestions.json"
    path.write_text(json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8")
    return suggestions


def _header_map(ws: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for cell in ws[1]:
        if cell.value is None:
            continue
        result[str(cell.value).strip().lower()] = int(cell.column)
    return result


def _first_col(headers: dict[str, int], names: list[str]) -> int | None:
    for name in names:
        hit = headers.get(name.lower())
        if hit is not None:
            return hit
    return None


def _cell_text(value: Any) -> str:
    return "" if value is None else str(value)


def _project_issue(
    sheet: str,
    row: int,
    check_type: str,
    message: str,
    translation: str,
    severity: str = "hard",
) -> dict[str, Any]:
    return {
        "source": "project_harness",
        "rule_source": "project_harness",
        "severity": severity,
        "sheet": sheet,
        "row": row,
        "check_type": check_type,
        "message": message,
        "translation": translation,
    }


def _improvement_item(category: str, run_id: str, title: str, detail: str) -> dict[str, Any]:
    return {
        "id": db.new_id("imp"),
        "category": category,
        "run_id": run_id,
        "title": title,
        "detail": detail,
        "status": "pending_review",
        "created_at": db.now_iso(),
    }


async def translate_run(run_id: str, request: Any) -> dict[str, Any]:
    run = db.get_run(run_id)
    if run["language"] != "en":
        db.update_run(run_id, status="needs_input", metadata={**run.get("metadata", {}), "reason": "v1 supports EN translation only"})
        return {"run": db.get_run(run_id), "artifacts": []}
    project = db.get_project(run["project_id"])
    metadata = run.get("metadata", {})
    input_artifact = db.get_artifact(metadata["input_artifact_id"])
    settings = load_settings()
    if request.provider:
        settings["provider"] = request.provider
    if request.protocol:
        settings["protocol"] = request.protocol
    if getattr(request, "preset", None):
        settings["preset"] = request.preset
    batch_size = int(request.batch_size or metadata.get("batch_size") or settings.get("batch_size") or 90)
    batch_size = max(1, min(batch_size, 200))
    effective_provider = str(settings.get("provider") or "mock")
    allow_mock = bool(getattr(request, "allow_mock", False)) or str(project.get("name", "")).startswith("E2E ")
    if effective_provider == "mock" and not allow_mock:
        db.update_run(
            run_id,
            status="needs_input",
            metadata={**metadata, "reason": "mock provider is blocked for real project translation"},
        )
        return {"run": db.get_run(run_id), "artifacts": [], "quality": None}
    if effective_provider in {"openai", "anthropic"} and not settings.get("api_key"):
        db.update_run(
            run_id,
            status="needs_input",
            metadata={**metadata, "reason": f"{effective_provider} api_key is required for formal translation"},
        )
        return {"run": db.get_run(run_id), "artifacts": [], "quality": None}

    db.update_run(run_id, status="running")
    work_dir = run_dir(run_id) / "translation"
    work_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = work_dir / "snapshots"
    glossary_snapshot = create_project_glossary_snapshot(project["id"], run_id, snapshot_dir)
    snapshots = create_prompt_and_harness_snapshots(project["id"], run_id, snapshot_dir)
    prompt = snapshots["prompt"]
    prompt_snapshot = snapshots["prompt_artifact"]
    harness_snapshot_artifact = snapshots["harness_artifact"]
    harness_snapshot = snapshots["harness_snapshot"]

    prepare_args = [
        sys.executable,
        str(LOCALIZATION_ROOT / "scripts" / "run_translation_harness.py"),
        "--input",
        input_artifact["path"],
        "--lang",
        "en",
        "--output-dir",
        str(work_dir),
        "--style-hint-file",
        str(snapshots["prompt_path"]),
        "--term-base",
        glossary_snapshot["path"],
    ]
    try:
        run_subprocess(prepare_args, LOCALIZATION_ROOT, run_id)
        workpack_path = work_dir / "translation_workpack.jsonl"
        rows = read_jsonl(workpack_path)
        translated_rows: list[dict[str, Any]] = []
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            db.add_event(run_id, f"translating batch {start // batch_size + 1}: rows={len(batch)}")
            items = await translate_batch(batch, settings, prompt, provider_override=request.provider, protocol_override=request.protocol)
            translated_rows.extend([{"id": item.id, "translation": item.translation} for item in items])
        response_path = work_dir / "translation_response.jsonl"
        write_jsonl(response_path, translated_rows)
        db.add_artifact(project["id"], "Translation response JSONL", response_path, "translation_response", run_id=run_id, mime="application/jsonl")

        apply_args = [
            sys.executable,
            str(LOCALIZATION_ROOT / "scripts" / "run_translation_harness.py"),
            "--input",
            input_artifact["path"],
            "--lang",
            "en",
            "--output-dir",
            str(work_dir),
            "--response",
            str(response_path),
            "--term-base",
            glossary_snapshot["path"],
        ]
        apply_proc = run_subprocess(apply_args, LOCALIZATION_ROOT, run_id)
        parsed = parse_key_output(apply_proc.stdout)
        raw_workbook = Path(parsed.get("final_workbook", ""))
        raw_artifact = db.add_artifact(
            project["id"],
            "Raw translated workbook",
            raw_workbook,
            "raw_translated_workbook",
            run_id=run_id,
            origin="generated",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            metadata={"language": "en", "source_workbook": input_artifact["id"]},
        )
        qa_result = run_localization_qa(
            project=project,
            run_id=run_id,
            workbook_path=raw_workbook,
            output_dir=work_dir / "qa",
            glossary_snapshot=glossary_snapshot,
            harness_snapshot=harness_snapshot,
            workbook_artifact=raw_artifact,
            run_metadata=metadata,
        )
        status = "passed" if qa_result["quality_summary"]["passed"] else "failed"
        artifacts = [
            raw_artifact,
            db.add_artifact(project["id"], "Translation manifest", work_dir / "translation_manifest.json", "translation_manifest", run_id=run_id, mime="application/json"),
            glossary_snapshot,
            prompt_snapshot,
            harness_snapshot_artifact,
            *qa_result["artifacts"],
        ]
        input_artifacts = {
            "source_workbook": input_artifact["id"],
            "raw_translated_workbook": raw_artifact["id"],
            "translation_workbook": raw_artifact["id"],
            "glossary_snapshot": glossary_snapshot["id"],
            "prompt_snapshot": prompt_snapshot["id"],
            "harness_snapshot": harness_snapshot_artifact["id"],
        }
        if qa_result.get("qa_final_artifact"):
            input_artifacts["qa_final_workbook"] = qa_result["qa_final_artifact"]["id"]
            input_artifacts["translation_workbook"] = qa_result["qa_final_artifact"]["id"]
        db.update_run(
            run_id,
            status=status,
            metadata={
                **metadata,
                "task_origin": metadata.get("task_origin") or "translation_run",
                "input_artifacts": input_artifacts,
                "quality": qa_result["quality"],
                "project_harness_quality": qa_result["project_harness_quality"],
                "semantic_qa": qa_result["semantic_qa"],
                "quality_summary": qa_result["quality_summary"],
                "harness": harness_snapshot["summary"],
                "model": {
                    "provider": settings.get("provider"),
                    "protocol": settings.get("protocol"),
                    "preset": settings.get("preset"),
                    "model": settings.get("model"),
                    "reasoning_effort": settings.get("reasoning_effort"),
                },
                "batch_size": batch_size,
            },
        )
        return {
            "run": db.get_run(run_id),
            "artifacts": artifacts,
            "quality": qa_result["quality"],
            "project_harness_quality": qa_result["project_harness_quality"],
            "quality_summary": qa_result["quality_summary"],
        }
    except Exception as exc:
        db.add_event(run_id, str(exc), level="error")
        db.update_run(run_id, status="failed", metadata={**metadata, "error": str(exc)})
        raise


def run_translate_sync(run_id: str, request: Any) -> dict[str, Any]:
    return asyncio.run(translate_run(run_id, request))
