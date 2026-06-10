from __future__ import annotations

import asyncio
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import Workbook, load_workbook

from .. import db
from ..config import GLOSSARY_ROOT, REAL_PROVIDERS, TEST_FAKE_PROVIDER, load_settings, normalize_provider_name
from ..languages import alt_aliases, language_spec, normalize_language, require_supported_language, target_aliases
from ..providers import call_text, translate_batch
from ..translation_batches import manage_project_prompt_context as _manage_project_prompt_context
from . import jsonl_helpers as _jsonl_helpers
from .common import _CJK_RE, project_dir, run_dir
from .materials import analyze_assets
from .naming import _safe_delivery_name, _safe_source_stem, _today_stamp, _visible_language_code
from .announcement_segments import _read_language_table_rows
from .qa import _parse_semantic_qa_payload
from .subprocess_runner import parse_key_output, run_subprocess, user_facing_error
from .table_helpers import (
    LANGUAGE_ORDER,
    _auto_language_indices,
    _column_index,
    _normalized_header_indices,
    _read_glossary_rows,
    _value_at,
    _wide_source_key,
)

_LARGE_LANGUAGE_TABLE_ROW_THRESHOLD = 1000
COMPLETE_LANGUAGE_TABLE_GLOSSARY_IMPORT_MESSAGE = "这个文件看起来是完整语言表，不是项目术语表。请到「生成术语」或翻译流程 STEP5 做高频词扫描并生成术语候选，候选确认后才会进入项目术语库。"
COMPLETE_LANGUAGE_TABLE_PROJECT_MATERIAL_MESSAGE = "这个文件看起来是完整语言表，请上传到 STEP4「语言表」。它不会作为项目资料参与术语提取。"

def extract_glossary(project_id: str, request: Any) -> dict[str, Any]:
    project = db.get_project(project_id)
    artifact = db.get_artifact(request.input_artifact_id)
    language = require_supported_language(getattr(request, "language", "en") or "en")
    spec = language_spec(language)
    material_artifact_ids = list(getattr(request, "project_material_artifact_ids", []) or [])
    announcement_material_artifact_ids = list(getattr(request, "announcement_material_artifact_ids", []) or [])
    announcement_only = bool(getattr(request, "announcement_only", False))
    announcement_min_hit = max(1, int(getattr(request, "announcement_min_hit", 1) or 1))
    if announcement_only and not announcement_material_artifact_ids:
        raise ValueError("announcement_only requires announcement_material_artifact_ids")
    project_notes = [str(note).strip() for note in getattr(request, "project_notes", []) or [] if str(note).strip()]
    material_notes = analyze_assets(material_artifact_ids, load_settings()) if material_artifact_ids else []
    run = db.insert_run(
        project_id,
        kind="glossary",
        language=language,
        metadata={
            "input_artifact_id": request.input_artifact_id,
            "project_material_artifact_ids": material_artifact_ids,
            "announcement_material_artifact_ids": announcement_material_artifact_ids,
            "announcement_only": announcement_only,
            "announcement_min_hit": announcement_min_hit,
            "project_notes": project_notes,
            "project_material_notes": material_notes,
        },
    )
    db.update_run(run["id"], status="running")
    output_dir = run_dir(run["id"]) / "glossary"
    output_dir.mkdir(parents=True, exist_ok=True)
    input_path = Path(artifact["path"])
    detail_output = output_dir / f"{input_path.stem}_glossary_details.xlsx"
    final_suffix = f"{spec.target_header}_{spec.alt_header}" if spec.alt_header else spec.target_header
    final_output = output_dir / f"{input_path.stem}_ID_CN_{final_suffix}.xlsx"
    brief_output = output_dir / "project_brief.md"
    prompt_output = output_dir / "translation_prompt.txt"
    announcement_base = _safe_source_stem(input_path.name)
    announcement_output = output_dir / f"{announcement_base}_announcement_terms_{_today_stamp()}.xlsx" if announcement_material_artifact_ids else None
    ai_supplement = bool(getattr(request, "ai_supplement", False))
    ai_supplement_packet_output = output_dir / f"{announcement_base}_ai_supplement_packet_{_today_stamp()}.json" if ai_supplement else None
    ai_supplement_report_output = output_dir / f"{announcement_base}_ai_supplement_report_{_today_stamp()}.md" if ai_supplement else None
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
        "--curated-rules",
        str(project_dir(project_id) / "glossary" / "curated_terms.json"),
        "--observations-store",
        str(project_dir(project_id) / "glossary" / "observed_terms.json"),
    ]
    if not announcement_only:
        args.extend(
            [
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
            ]
        )
    if request.sheet:
        args.extend(["--sheet", request.sheet])
    if request.source_only:
        args.append("--source-only")
    if request.include_empty_final_terms:
        args.append("--include-empty-final-terms")
    for announcement_artifact_id in announcement_material_artifact_ids:
        announcement_artifact = db.get_artifact(announcement_artifact_id)
        args.extend(["--announcement-material", announcement_artifact["path"]])
    if announcement_output is not None:
        args.extend(["--announcement-output", str(announcement_output), "--announcement-min-hit", str(announcement_min_hit)])
    if ai_supplement:
        if not announcement_material_artifact_ids:
            raise ValueError("ai_supplement requires announcement_material_artifact_ids")
        args.append("--ai-supplement")
        if ai_supplement_packet_output is not None:
            args.extend(["--ai-supplement-packet-output", str(ai_supplement_packet_output)])
        if ai_supplement_report_output is not None:
            args.extend(["--ai-supplement-report-output", str(ai_supplement_report_output)])
        response_artifact_id = str(getattr(request, "ai_supplement_response_artifact_id", "") or "").strip()
        if response_artifact_id:
            response_artifact = db.get_artifact(response_artifact_id)
            if response_artifact["project_id"] != project_id:
                raise KeyError(response_artifact_id)
            args.extend(["--ai-supplement-provider", "file", "--ai-supplement-response", response_artifact["path"]])
        else:
            # The workbench owns provider calls via backend/app/providers.py.
            # Do not let the embedded CLI auto-read OPENAI_API_KEY and bypass
            # the configured GPT/Claude/Codex-relay settings.
            args.extend(["--ai-supplement-provider", "packet"])
    if not announcement_only:
        for material_artifact_id in material_artifact_ids:
            material_artifact = db.get_artifact(material_artifact_id)
            args.extend(["--project-material", material_artifact["path"]])
        for note in [*project_notes, *material_notes]:
            args.extend(["--project-note", note])
    try:
        proc = run_subprocess(args, GLOSSARY_ROOT, run["id"])
        parsed = parse_key_output(proc.stdout)
        artifacts = []
        backfill: dict[str, Any] = {}
        if not announcement_only:
            artifacts.extend(
                [
                    db.add_artifact(project_id, "Glossary details", detail_output, "glossary_detail", run_id=run["id"]),
                    db.add_artifact(project_id, f"ID CN {final_suffix} glossary", final_output, "glossary_final", run_id=run["id"]),
                    db.add_artifact(project_id, "Project brief", brief_output, "project_brief", run_id=run["id"], mime="text/markdown"),
                    db.add_artifact(project_id, "Translation prompt", prompt_output, "translation_prompt", run_id=run["id"], mime="text/plain"),
                ]
            )
            backfill = backfill_project_glossary_from_final(project_id, final_output, run["id"], language=language)
            if bool(getattr(request, "ai_candidate_supplement", True)):
                backfill["ai_supplement"] = supplement_language_table_glossary_candidates_with_ai(
                    project_id=project_id,
                    batch_id=str(backfill.get("batch_id") or ""),
                    input_path=input_path,
                    language=language,
                    run_id=run["id"],
                )
        if announcement_output is not None and announcement_output.exists():
            artifacts.append(
                db.add_artifact(
                    project_id,
                    "Announcement glossary lookup",
                    announcement_output,
                    "announcement_glossary",
                    run_id=run["id"],
                )
            )
        if ai_supplement_packet_output is not None and ai_supplement_packet_output.exists():
            artifacts.append(db.add_artifact(project_id, "公告 AI 补充包", ai_supplement_packet_output, "announcement_ai_supplement_packet", run_id=run["id"], mime="application/json"))
        if ai_supplement_report_output is not None and ai_supplement_report_output.exists():
            artifacts.append(db.add_artifact(project_id, "公告 AI 补充报告", ai_supplement_report_output, "announcement_ai_supplement_report", run_id=run["id"], mime="text/markdown"))
        if not announcement_only and prompt_output.exists():
            prompt = prompt_output.read_text(encoding="utf-8")
            db.update_project(project_id, {"prompt_text": prompt})
        db.update_run(
            run["id"],
            status="passed",
            metadata={
                "output": parsed,
                "glossary_backfill": backfill,
                "announcement": {
                    "material_artifact_ids": announcement_material_artifact_ids,
                    "only": announcement_only,
                    "output": str(announcement_output) if announcement_output else "",
                    "terms": int(parsed.get("ANNOUNCEMENT_TERMS") or 0),
                    "ai_supplement_packet": parsed.get("AI_SUPPLEMENT_PACKET_OUTPUT") or "disabled",
                    "ai_supplement_report": parsed.get("AI_SUPPLEMENT_REPORT_OUTPUT") or "disabled",
                },
            },
        )
        return {"run": db.get_run(run["id"]), "artifacts": artifacts, "output": parsed, "glossary_backfill": backfill}
    except Exception as exc:
        friendly = user_facing_error(exc)
        db.add_event(run["id"], friendly, level="error")
        db.update_run(run["id"], status="failed", metadata={"error": friendly})
        raise


def backfill_project_glossary_from_final(project_id: str, final_output: Path, run_id: str | None = None, language: str = "en") -> dict[str, Any]:
    """Stage generated high-frequency terms for review without changing the project glossary."""
    language = require_supported_language(language)
    result = {
        "candidates": 0,
        "unique_candidates": 0,
        "inserted": 0,
        "updated": 0,
        "skipped_existing": 0,
        "skipped_empty": 0,
        "skipped_duplicate": 0,
        "conflicts": 0,
        "pending_confirmation": 0,
        "batch_id": "",
    }
    if not final_output.exists():
        if run_id:
            db.add_event(run_id, "Glossary backfill skipped: generated ID/CN/EN/EN2 file was not found.", level="warn")
        return result

    # The embedded glossary extractor keeps legacy output headers as EN/EN2 even
    # when the source target column is KR/JP/etc. Interpret those generated
    # columns as the current run language only in this controlled backfill path.
    rows, _columns = _read_glossary_rows(final_output, limit=None, language=language, target_column="EN", target_alt_column="EN2")
    result["candidates"] = len(rows)

    existing: dict[str, dict[str, Any]] = {}
    for term in db.list_glossary_terms(project_id, language=language):
        source_key = _glossary_source_key(term.get("source"))
        if not source_key:
            continue
        current = existing.get(source_key)
        if current is None or _glossary_term_rank(term) < _glossary_term_rank(current):
            existing[source_key] = term

    deduped_rows: dict[str, dict[str, Any]] = {}
    for row in rows:
        source = str(row.get("source") or "").strip()
        source_key = _glossary_source_key(source)
        if not source_key:
            result["skipped_empty"] += 1
            continue
        current = deduped_rows.get(source_key)
        if current:
            result["skipped_duplicate"] += 1
            _fill_blank_glossary_fields(current, row)
            continue
        deduped_rows[source_key] = dict(row, source=source)

    result["unique_candidates"] = len(deduped_rows)
    batch = db.create_glossary_batch(
        project_id,
        run_id=run_id,
        source_artifact_id="",
        label=f"Glossary scan {datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d%H%M')}",
        metadata={"strategy": "stage_candidates_then_accept", "source": str(final_output)},
        language=language,
    )
    result["batch_id"] = batch["id"]
    if run_id:
        db.add_event(
            run_id,
            "Glossary backfill strategy: dedupe by normalized CN; stage only missing CN as review candidates; "
            "existing project glossary terms are skipped and never auto-filled.",
        )

    for source_key, row in deduped_rows.items():
        source = str(row.get("source") or "").strip()
        target = str(row.get("target") or "").strip()
        target_alt = str(row.get("target_alt") or "").strip()
        current = existing.get(source_key)
        if current:
            result["skipped_existing"] += 1
            existing[source_key] = current
            continue

        db.add_glossary_candidate(
            project_id,
            batch["id"],
            {
                "term_key": row.get("term_key", ""),
                "source": source,
                "target": target,
                "target_alt": target_alt,
                "language": language,
                "category": row.get("category", ""),
                "note": row.get("note", "") or ("高频词候选，需补译后人工确认" if not target and not target_alt else "高频词候选，需人工确认"),
                "action": "new",
            },
        )
        result["inserted"] += 1
        result["pending_confirmation"] += 1

    if run_id:
        db.add_event(
            run_id,
            "Glossary backfill result: "
            f"candidates={result['candidates']}, unique={result['unique_candidates']}, inserted={result['inserted']}, "
            f"updated={result['updated']}, existing={result['skipped_existing']}, duplicates={result['skipped_duplicate']}, "
            f"conflicts={result['conflicts']}, empty={result['skipped_empty']}.",
        )
    return result


def _language_table_ai_audit_rows(rows: list[dict[str, Any]], language: str, existing_sources: set[str], limit: int = 400) -> list[dict[str, str]]:
    selected: dict[str, dict[str, str]] = {}
    for row in rows:
        source = str(row.get("source") or "").strip()
        source_key = _glossary_source_key(source)
        if not source or source_key in existing_sources or source_key in selected:
            continue
        if not _CJK_RE.search(source):
            continue
        translations = row.get("translations") if isinstance(row.get("translations"), dict) else {}
        selected[source_key] = {
            "id": str(row.get("id") or "").strip(),
            "source": source,
            "translation": str((translations or {}).get(language) or "").strip(),
        }
    values = list(selected.values())
    values.sort(key=lambda item: (0 if 2 <= len(item["source"]) <= 24 else 1, len(item["source"]), item["source"]))
    return values[:limit]


def _glossary_ai_supplement_prompt(
    *,
    project: dict[str, Any],
    language: str,
    candidates: list[dict[str, Any]],
    audit_rows: list[dict[str, str]],
) -> str:
    spec = language_spec(language)
    profile = project.get("profile") or {}
    prompt_text = str((profile.get("prompts_by_language") or {}).get(language) or project.get("prompt_text") or "").strip()
    prompt_text = _manage_project_prompt_context(prompt_text, load_settings())
    candidate_sources = [
        {"cn": item.get("source"), "translation": item.get("target")}
        for item in candidates[:500]
        if str(item.get("source") or "").strip()
    ]
    packet = {
        "task": "language_table_glossary_ai_supplement",
        "target_language": spec.prompt_name,
        "visible_language": spec.target_header,
        "project": {
            "name": project.get("name", ""),
            "type": project.get("type", ""),
            "profile": {
                key: profile.get(key)
                for key in ("game_type", "target_audience", "content_scope", "translation_style", "tone")
                if profile.get(key)
            },
            "prompt": prompt_text,
        },
        "existing_candidates": candidate_sources,
        "source_rows_for_audit": audit_rows,
        "response_schema": {
            "supplement_terms": [
                {
                    "cn": "必须逐字出现在 source_rows_for_audit.source 中的中文术语",
                    "translation": f"{spec.target_header} 建议译文；不确定则留空",
                    "confidence": "medium|high",
                    "reason": "为什么本地规则漏掉且值得人工审核",
                    "evidence_ids": ["source_rows_for_audit.id"],
                }
            ]
        },
    }
    return (
        "你在做游戏语言表术语候选的漏词审计。本地脚本已经先按规则扫描了一批候选，"
        "你只补充明显漏掉的游戏专名、系统名、玩法名、道具/角色/活动名或关键 UI 术语。\n"
        "硬规则：\n"
        "1. 只能从 source_rows_for_audit 里补，cn 必须逐字出现在某条 source 中。\n"
        "2. 不要补整句、长句、纯标点、普通动词、泛泛说明词。\n"
        "3. 不要重复 existing_candidates 里已有的 CN。\n"
        "4. 有同一行译文证据时给 translation；不确定就留空，交给人工。\n"
        "5. 只返回 confidence 为 medium 或 high 的项，最多 30 条。\n"
        "6. 返回严格 JSON 对象，不要 markdown。\n\n"
        f"Packet JSON:\n{json.dumps(packet, ensure_ascii=False, indent=2)}"
    )


def _normalize_glossary_ai_supplement_terms(payload: dict[str, Any]) -> list[dict[str, Any]]:
    terms = payload.get("supplement_terms")
    if not isinstance(terms, list):
        return []
    return [item for item in terms if isinstance(item, dict)]


def supplement_language_table_glossary_candidates_with_ai(
    *,
    project_id: str,
    batch_id: str,
    input_path: Path,
    language: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    language = require_supported_language(language)
    result: dict[str, Any] = {
        "status": "skipped",
        "added": 0,
        "reviewed_rows": 0,
        "provider": "",
        "reason": "",
    }
    if not batch_id:
        result["reason"] = "no_candidate_batch"
        return result

    settings = load_settings()
    provider = normalize_provider_name(settings.get("provider"))
    result["provider"] = provider
    if provider == TEST_FAKE_PROVIDER:
        result["reason"] = "test_provider"
        return result
    if provider in REAL_PROVIDERS and not str(settings.get("api_key") or "").strip():
        result["reason"] = "api_key_missing"
        if run_id:
            db.add_event(run_id, "AI glossary supplement skipped: API key is not configured.", level="warn")
        return result

    project = db.get_project(project_id)
    existing_sources = {
        _glossary_source_key(item.get("source"))
        for item in db.list_glossary_terms(project_id, language=language)
        if _glossary_source_key(item.get("source"))
    }
    batch_candidates = db.list_glossary_candidates(project_id, batch_id=batch_id, language=language)
    existing_sources.update(
        _glossary_source_key(item.get("source"))
        for item in batch_candidates
        if _glossary_source_key(item.get("source"))
    )
    audit_rows = _language_table_ai_audit_rows(_read_language_table_rows(input_path, [language]), language, existing_sources)
    result["reviewed_rows"] = len(audit_rows)
    if not audit_rows:
        result["reason"] = "no_audit_rows"
        return result

    prompt = _glossary_ai_supplement_prompt(
        project=project,
        language=language,
        candidates=batch_candidates,
        audit_rows=audit_rows,
    )
    try:
        response_text = call_text(settings, prompt, system="Return strict JSON only.")
        payload = _parse_semantic_qa_payload(response_text)
    except Exception as exc:
        result["status"] = "provider_error"
        result["reason"] = user_facing_error(exc)
        if run_id:
            db.add_event(run_id, f"AI glossary supplement failed: {result['reason']}", level="warn")
        return result

    evidence_by_id = {str(item.get("id") or "").strip(): item for item in audit_rows if str(item.get("id") or "").strip()}
    evidence_sources = [item["source"] for item in audit_rows]
    added = 0
    skipped = 0
    for term in _normalize_glossary_ai_supplement_terms(payload):
        cn = str(term.get("cn") or "").strip()
        source_key = _glossary_source_key(cn)
        confidence = str(term.get("confidence") or "").strip().lower()
        if not cn or source_key in existing_sources or confidence not in {"medium", "high"}:
            skipped += 1
            continue
        evidence_ids = term.get("evidence_ids") if isinstance(term.get("evidence_ids"), list) else []
        evidence_rows = [evidence_by_id.get(str(item).strip()) for item in evidence_ids]
        evidence_rows = [item for item in evidence_rows if item]
        if evidence_rows:
            appears = any(cn in str(item.get("source") or "") for item in evidence_rows)
        else:
            appears = any(cn in source for source in evidence_sources)
        if not appears:
            skipped += 1
            continue
        translation = str(term.get("translation") or "").strip()
        note_bits = ["AI 漏词补充候选，需人工确认"]
        if confidence:
            note_bits.append(f"置信度 {confidence}")
        reason = str(term.get("reason") or "").strip()
        if reason:
            note_bits.append(reason)
        db.add_glossary_candidate(
            project_id,
            batch_id,
            {
                "term_key": str((evidence_rows[0] or {}).get("id") or "") if evidence_rows else "",
                "source": cn,
                "target": translation,
                "target_alt": "",
                "language": language,
                "category": "",
                "note": "；".join(note_bits),
                "action": "new",
                "translation_status": "suggested" if translation else "needs_translation",
                "translation_source": "ai_supplement" if translation else "none",
                "metadata": {
                    "ai_supplement": {
                        "provider": provider,
                        "model": settings.get("model") or "",
                        "confidence": confidence,
                        "reason": reason,
                        "evidence_ids": evidence_ids,
                    }
                },
            },
        )
        existing_sources.add(source_key)
        added += 1

    result.update({"status": "passed", "added": added, "skipped": skipped, "reason": ""})
    if run_id:
        db.add_event(run_id, f"AI glossary supplement added {added} candidates, skipped {skipped}.")
    return result


async def translate_missing_glossary_candidates(project_id: str, batch_id: str) -> dict[str, Any]:
    project = db.get_project(project_id)
    batch = db.get_glossary_batch(batch_id)
    if batch["project_id"] != project_id:
        raise KeyError(batch_id)
    language = require_supported_language(batch.get("language") or "en")
    settings = load_settings()
    provider = normalize_provider_name(settings.get("provider"))
    if provider in REAL_PROVIDERS and not settings.get("api_key"):
        raise ValueError(f"{provider} api_key is required to translate glossary candidates")

    pending = db.list_glossary_candidates(project_id, batch_id=batch_id, status="pending", language=language)
    missing = [candidate for candidate in pending if not str(candidate.get("target") or "").strip()]
    if not missing:
        return {
            "batch": batch,
            "translated_count": 0,
            "skipped_count": len(pending),
            "candidates": db.list_glossary_candidates(project_id, batch_id=batch_id, language=language),
        }

    rows: list[dict[str, Any]] = []
    id_to_candidate: dict[int, dict[str, Any]] = {}
    for index, candidate in enumerate(missing, start=1):
        rows.append(
            {
                "id": index,
                "source": str(candidate.get("source") or ""),
                "text_type": "glossary_term_candidate",
                "term_key": str(candidate.get("term_key") or ""),
                "note": str(candidate.get("note") or ""),
            }
        )
        id_to_candidate[index] = candidate

    prompt = _glossary_candidate_translation_prompt(project, rows, language=language)
    try:
        items = await translate_batch(rows, settings, prompt)
    except Exception as exc:
        raise ValueError(f"glossary candidate translation failed: {user_facing_error(exc)}") from exc
    translated_count = 0
    for item in items:
        candidate = id_to_candidate.get(int(item.id))
        if candidate is None:
            continue
        translation = str(item.translation or "").strip()
        if not translation:
            continue
        metadata = dict(candidate.get("metadata") or {})
        metadata["model"] = {
            "provider": provider,
            "model": settings.get("model") or "",
            "preset": settings.get("preset") or "",
            "translated_at": db.now_iso(),
        }
        db.update_glossary_candidate(
            candidate["id"],
            {
                "target": translation,
                "translation_status": "suggested",
                "translation_source": "model",
                "metadata": metadata,
            },
        )
        translated_count += 1

    if batch.get("run_id"):
        db.add_event(batch["run_id"], f"Glossary candidate translation filled {translated_count} missing {language.upper()} values.")
    return {
        "batch": db.get_glossary_batch(batch_id),
        "translated_count": translated_count,
        "skipped_count": len(pending) - len(missing),
        "candidates": db.list_glossary_candidates(project_id, batch_id=batch_id, language=language),
    }


def translate_missing_glossary_candidates_sync(project_id: str, batch_id: str) -> dict[str, Any]:
    return asyncio.run(translate_missing_glossary_candidates(project_id, batch_id))


def _glossary_candidate_translation_prompt(project: dict[str, Any], rows: list[dict[str, Any]], language: str = "en") -> str:
    language = require_supported_language(language)
    spec = language_spec(language)
    profile = project.get("profile") or {}
    prompt_text = str((profile.get("prompts_by_language") or {}).get(language) or project.get("prompt_text") or "").strip()
    prompt_text = _manage_project_prompt_context(prompt_text, load_settings())
    profile_summary = {
        key: profile.get(key)
        for key in ("game_type", "target_audience", "content_scope", "translation_style", "tone", "language_assets")
        if profile.get(key)
    }
    existing_terms = [
        {"source": term.get("source"), "target": term.get("target"), "target_alt": term.get("target_alt")}
        for term in db.list_glossary_terms(project["id"], language=language)[:200]
        if str(term.get("source") or "").strip() and str(term.get("target") or "").strip()
    ]
    term_instruction = (
        f"Translate only the {spec.target_header} term. Do not create {spec.alt_header}, notes, categories, explanations, or markdown. "
        if spec.alt_header
        else f"Translate only the {spec.target_header} term. Do not create notes, categories, explanations, or markdown. "
    )
    return (
        f"Translate short game glossary term candidates from Chinese to {spec.prompt_name}. "
        "Return JSONL only; each line must be {\"id\": number, \"translation\": string}. "
        f"{term_instruction}"
        "Keep UI terms concise and consistent with existing glossary.\n\n"
        f"Project: {project.get('name', '')}\n"
        f"Profile: {json.dumps(profile_summary, ensure_ascii=False)}\n"
        f"Project prompt:\n{prompt_text}\n\n"
        f"Existing glossary examples:\n{json.dumps(existing_terms, ensure_ascii=False)}\n\n"
        f"Candidates:\n" + "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return _jsonl_helpers.read_jsonl(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    _jsonl_helpers.write_jsonl(path, rows)


def _glossary_source_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).casefold()


def _glossary_term_rank(term: dict[str, Any]) -> tuple[int, int, int]:
    has_translation = bool(str(term.get("target") or "").strip() or str(term.get("target_alt") or "").strip())
    confirmed = bool(term.get("confirmed"))
    curated_source = str(term.get("source_type") or "") in {"manual", "imported", "curated"}
    return (0 if confirmed else 1, 0 if has_translation else 1, 0 if curated_source else 1)


def _fill_blank_glossary_fields(base: dict[str, Any], incoming: dict[str, Any]) -> None:
    for field in ("target", "target_alt", "category", "note"):
        if not str(base.get(field) or "").strip() and str(incoming.get(field) or "").strip():
            base[field] = incoming.get(field, "")



def is_complete_language_table_for_glossary_import(path: Path, sheet: str | None = None, row_threshold: int = _LARGE_LANGUAGE_TABLE_ROW_THRESHOLD) -> bool:
    if path.suffix.lower() not in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        return False
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        header_row = next(ws.iter_rows(min_row=1, max_row=1), None)
        if header_row is None:
            return False
        headers = [str(cell.value or "").strip() for cell in header_row]
        normalized = _normalized_header_indices(headers)
        term_key_idx = _column_index(normalized, None, ["id", "key", "编号", "序号"], required=False)
        source_idx = _column_index(normalized, None, ["source", "original", "cn", "zh", "chinese", "原文", "中文", "简体中文"], required=False)
        if term_key_idx is None or source_idx is None:
            return False
        reserved = {term_key_idx, source_idx}
        language_indices = _auto_language_indices(headers, reserved)
        if not language_indices:
            return False
        source_rows = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            if _value_at(row, source_idx):
                source_rows += 1
                if source_rows > row_threshold:
                    return True
        return False
    finally:
        wb.close()


def guard_complete_language_table_for_glossary_import(path: Path, sheet: str | None = None) -> None:
    if is_complete_language_table_for_glossary_import(path, sheet=sheet):
        raise ValueError(COMPLETE_LANGUAGE_TABLE_GLOSSARY_IMPORT_MESSAGE)


def guard_complete_language_table_for_project_material(path: Path, sheet: str | None = None) -> None:
    if is_complete_language_table_for_glossary_import(path, sheet=sheet):
        raise ValueError(COMPLETE_LANGUAGE_TABLE_PROJECT_MATERIAL_MESSAGE)


def preview_glossary_import(project_id: str, request: Any, import_all: bool = False) -> dict[str, Any]:
    project = db.get_project(project_id)
    _ = project
    artifact = db.get_artifact(request.artifact_id)
    path = Path(artifact["path"])
    guard_complete_language_table_for_glossary_import(path, sheet=getattr(request, "sheet", None))
    language = require_supported_language(getattr(request, "language", "en") or "en")
    auto_languages = bool(getattr(request, "auto_languages", True))
    if auto_languages and not getattr(request, "target_column", None) and not getattr(request, "target_alt_column", None):
        rows, columns, languages = _read_multilingual_glossary_rows(
            path,
            sheet=getattr(request, "sheet", None),
            term_key_column=getattr(request, "term_key_column", None),
            source_column=getattr(request, "source_column", None),
            category_column=getattr(request, "category_column", None),
            note_column=getattr(request, "note_column", None),
            limit=None if import_all else int(getattr(request, "limit", 100) or 100),
        )
        if languages:
            return {"artifact": artifact, "columns": columns, "rows": rows, "total_rows": len(rows), "language": "auto", "languages": languages}
    rows, columns = _read_glossary_rows(
        path,
        sheet=getattr(request, "sheet", None),
        term_key_column=getattr(request, "term_key_column", None),
        source_column=getattr(request, "source_column", None),
        target_column=getattr(request, "target_column", None),
        target_alt_column=getattr(request, "target_alt_column", None),
        category_column=getattr(request, "category_column", None),
        note_column=getattr(request, "note_column", None),
        language=language,
        limit=None if import_all else int(getattr(request, "limit", 100) or 100),
    )
    return {"artifact": artifact, "columns": columns, "rows": rows, "total_rows": len(rows), "language": language}


def import_glossary(project_id: str, request: Any) -> dict[str, Any]:
    preview = preview_glossary_import(project_id, request, import_all=True)
    language = preview["language"]
    payloads = []
    for row in preview["rows"]:
        if not row.get("source"):
            continue
        payloads.append(
            {
                "term_key": row.get("term_key", ""),
                "source": row.get("source", ""),
                "target": row.get("target", ""),
                "target_alt": row.get("target_alt", ""),
                "language": row.get("language") or language,
                "category": row.get("category", ""),
                "note": row.get("note", ""),
                "source_type": "imported",
                "confirmed": True,
            }
        )
    imported = db.upsert_glossary_terms_bulk(project_id, payloads)
    return {"imported_count": len(imported), "terms": imported, "preview": preview, "languages": preview.get("languages") or ([language] if language != "auto" else [])}


def export_glossary(project_id: str, fmt: str, language: str | None = None) -> dict[str, Any] | Path:
    project = db.get_project(project_id)
    language = require_supported_language(language or "en") if language else None
    terms = db.list_glossary_terms(project_id, language=language)
    if fmt == "json":
        return {
            "project_id": project_id,
            "language": language,
            "terms": [dict(zip(("term_key", "source", "target", "target_alt", "category", "note"), _glossary_export_row(term))) | {"language": term.get("language", "en")} for term in terms],
        }
    output_dir = project_dir(project_id) / "glossary" / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = _export_language_suffix(language)
    if language:
        columns = ["ID", "CN", _visible_language_code(language), *(["EN2"] if language == "en" else []), "分类", "备注"]
        rows = [_glossary_export_row(term, include_alt=language == "en") for term in terms]
    else:
        wide = list_glossary_wide(project_id)
        languages = list(wide.get("languages") or [])
        columns = ["ID", "CN", *_wide_language_columns(languages), "分类", "备注"]
        rows = _glossary_wide_export_rows(wide, languages)
    if fmt == "csv":
        path = output_dir / _export_filename(project, "glossary", suffix, "csv")
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(columns)
            writer.writerows(rows)
        return path
    path = output_dir / _export_filename(project, "glossary", suffix, "xlsx")
    wb = Workbook()
    ws = wb.active
    ws.title = "Glossary"
    ws.append(columns)
    for row in rows:
        ws.append(row)
    wb.save(path)
    wb.close()
    return path


def _export_language_suffix(language: str | None) -> str:
    return _visible_language_code(language) if language else "ALL"


def _export_filename(project: dict[str, Any], kind: str, suffix: str, ext: str) -> str:
    return f"{_safe_delivery_name(project['name'])}_{kind}_{suffix}_{_today_stamp()}.{ext}"


def _glossary_export_row(term: dict[str, Any], *, include_alt: bool = True) -> list[Any]:
    row = [
        term.get("term_key", ""),
        term.get("source", ""),
        term.get("target", ""),
    ]
    if include_alt:
        row.append(term.get("target_alt", ""))
    row.extend([term.get("category", ""), term.get("note", "")])
    return row


def _wide_language_columns(languages: list[str]) -> list[str]:
    columns: list[str] = []
    for code in languages:
        columns.append(_visible_language_code(code))
        if code == "en":
            columns.append("EN2")
    return columns


def _glossary_wide_export_rows(wide: dict[str, Any], languages: list[str]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for row in wide["rows"]:
        translations = row.get("translations") or {}
        values = [row.get("term_key", ""), row.get("source", "")]
        for code in languages:
            entry = translations.get(code) or {}
            values.append(entry.get("target", ""))
            if code == "en":
                values.append(entry.get("target_alt", ""))
        values.extend([row.get("category", ""), row.get("note", "")])
        rows.append(values)
    return rows


def import_translation_archive(project_id: str, request: Any, source_type: str = "imported") -> dict[str, Any]:
    language = require_supported_language(getattr(request, "language", "en") or "en")
    artifact = db.get_artifact(request.artifact_id)
    if artifact["project_id"] != project_id:
        raise KeyError("artifact")
    if bool(getattr(request, "auto_languages", True)) and not getattr(request, "target_column", None) and not getattr(request, "target_alt_column", None):
        rows = _read_multilingual_translation_rows(
            Path(artifact["path"]),
            sheet=getattr(request, "sheet", None),
            id_column=getattr(request, "id_column", None),
            source_column=getattr(request, "source_column", None),
            note_column=getattr(request, "note_column", None),
            source_artifact_id=artifact["id"],
            source_type=source_type,
        )
        if not rows:
            rows = _read_translation_rows(
                Path(artifact["path"]),
                sheet=getattr(request, "sheet", None),
                id_column=getattr(request, "id_column", None),
                source_column=getattr(request, "source_column", None),
                target_column=getattr(request, "target_column", None),
                target_alt_column=getattr(request, "target_alt_column", None),
                note_column=getattr(request, "note_column", None),
                language=language,
                source_artifact_id=artifact["id"],
                source_type=source_type,
            )
    else:
        rows = _read_translation_rows(
            Path(artifact["path"]),
            sheet=getattr(request, "sheet", None),
            id_column=getattr(request, "id_column", None),
            source_column=getattr(request, "source_column", None),
            target_column=getattr(request, "target_column", None),
            target_alt_column=getattr(request, "target_alt_column", None),
            note_column=getattr(request, "note_column", None),
            language=language,
            source_artifact_id=artifact["id"],
            source_type=source_type,
        )
    imported = db.upsert_translation_entries_bulk(project_id, [row for row in rows if row.get("source") or row.get("target")])
    languages = [code for code in LANGUAGE_ORDER if any(row.get("language") == code for row in rows)]
    return {"project_id": project_id, "artifact_id": artifact["id"], "imported_count": len(imported), "entries": imported, "languages": languages or [language]}


def archive_translation_artifact(project_id: str, artifact_id: str, language: str = "en", source_type: str = "qa_passed") -> dict[str, Any]:
    class Request:
        pass

    request = Request()
    request.artifact_id = artifact_id
    request.language = language
    request.sheet = None
    request.id_column = None
    request.source_column = None
    request.target_column = None
    request.target_alt_column = None
    request.note_column = None
    return import_translation_archive(project_id, request, source_type=source_type)


def export_translation_archive(project_id: str, fmt: str, language: str | None = None) -> dict[str, Any] | Path:
    project = db.get_project(project_id)
    language = require_supported_language(language or "en") if language else None
    entries = db.list_translation_entries(project_id, language=language)
    if fmt == "json":
        return {"project_id": project_id, "language": language, "entries": [_translation_export_payload(entry) for entry in entries]}
    output_dir = project_dir(project_id) / "translations" / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = _export_language_suffix(language)
    if language:
        columns = ["ID", "CN", _visible_language_code(language), *(["EN2"] if language == "en" else []), "备注"]
        rows = [_translation_export_row(entry, include_alt=language == "en") for entry in entries]
    else:
        wide = list_translation_archive_wide(project_id)
        languages = list(wide.get("languages") or [])
        columns = ["ID", "CN", *_wide_language_columns(languages), "备注"]
        rows = _translation_wide_export_rows(wide, languages)
    if fmt == "csv":
        path = output_dir / _export_filename(project, "translations", suffix, "csv")
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(columns)
            writer.writerows(rows)
        return path
    path = output_dir / _export_filename(project, "translations", suffix, "xlsx")
    wb = Workbook()
    ws = wb.active
    ws.title = "Translations"
    ws.append(columns)
    for row in rows:
        ws.append(row)
    wb.save(path)
    wb.close()
    return path


def list_glossary_wide(project_id: str) -> dict[str, Any]:
    db.get_project(project_id)
    rows = _wide_rows(
        db.list_glossary_terms(project_id),
        key_field="term_key",
        shared_fields=("term_key", "category", "note"),
    )
    return {"project_id": project_id, **rows}


def list_translation_archive_wide(project_id: str) -> dict[str, Any]:
    db.get_project(project_id)
    rows = _wide_rows(
        db.list_translation_entries(project_id),
        key_field="entry_key",
        shared_fields=("entry_key", "note"),
    )
    return {"project_id": project_id, **rows}


def _wide_rows(items: list[dict[str, Any]], *, key_field: str, shared_fields: tuple[str, ...]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        source_key = _wide_source_key(item.get("source"))
        if not source_key:
            continue
        grouped.setdefault(source_key, []).append(item)

    wide_rows: list[dict[str, Any]] = []
    coverage: dict[str, int] = {}
    for source_key, group in grouped.items():
        translations: dict[str, dict[str, Any]] = {}
        for code in LANGUAGE_ORDER:
            candidates = [item for item in group if normalize_language(item.get("language") or "en") == code and (str(item.get("target") or "").strip() or str(item.get("target_alt") or "").strip())]
            if not candidates:
                continue
            selected = sorted(candidates, key=lambda item: str(item.get("updated_at") or ""), reverse=True)[0]
            payload = {
                "id": selected.get("id", ""),
                "language": code,
                "target": selected.get("target", ""),
                "target_alt": selected.get("target_alt", ""),
            }
            translations[code] = payload
            coverage[code] = coverage.get(code, 0) + 1
        shared = {field: _first_non_blank(group, field) for field in shared_fields}
        wide_rows.append(
            {
                "source_key": source_key,
                "source": _first_non_blank(group, "source"),
                **shared,
                "translations": translations,
                "languages": [code for code in LANGUAGE_ORDER if code in translations],
                "conflicts": _wide_conflicts(group, ("source", *shared_fields)),
            }
        )

    languages = [code for code in LANGUAGE_ORDER if coverage.get(code, 0) > 0]
    wide_rows.sort(key=lambda row: (str(row.get("source") or ""), str(row.get(key_field) or "")))
    return {"languages": languages, "coverage": {code: coverage[code] for code in languages}, "row_count": len(wide_rows), "rows": wide_rows}



def _first_non_blank(rows: list[dict[str, Any]], field: str) -> str:
    for row in rows:
        value = str(row.get(field) or "").strip()
        if value and value != "-":
            return value
    return ""


def _wide_conflicts(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for field in fields:
        values: list[str] = []
        for row in rows:
            value = str(row.get(field) or "").strip()
            if value and value != "-" and value not in values:
                values.append(value)
        if len(values) > 1:
            conflicts.append({"field": field, "values": values})
    return conflicts



def _read_multilingual_glossary_rows(
    path: Path,
    sheet: str | None = None,
    term_key_column: str | None = None,
    source_column: str | None = None,
    category_column: str | None = None,
    note_column: str | None = None,
    limit: int | None = 100,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    if path.suffix.lower() not in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        return [], {}, []
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        headers = [str(cell.value or "").strip() for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        normalized = _normalized_header_indices(headers)
        term_key_idx = _column_index(normalized, term_key_column, ["id", "key", "编号", "序号"], required=False)
        source_idx = _column_index(normalized, source_column, ["source", "original", "cn", "zh", "chinese", "term", "原文", "中文", "术语"])
        category_idx = _column_index(normalized, category_column, ["category", "type", "分类", "类别", "类型"], required=False)
        note_idx = _column_index(normalized, note_column, ["note", "notes", "comment", "备注"], required=False)
        reserved = {index for index in (term_key_idx, source_idx, category_idx, note_idx) if index is not None}
        language_indices = _auto_language_indices(headers, reserved)
        if not language_indices:
            return [], {}, []
        rows: list[dict[str, Any]] = []
        source_rows = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            source = _value_at(row, source_idx)
            if not source:
                continue
            source_rows += 1
            if limit is not None and source_rows > limit:
                break
            for code, (target_idx, alt_idx) in language_indices.items():
                target = _value_at(row, target_idx)
                target_alt = _value_at(row, alt_idx) if code == "en" else ""
                if not target and not target_alt:
                    continue
                rows.append(
                    {
                        "term_key": _value_at(row, term_key_idx) if term_key_idx is not None else "",
                        "source": source,
                        "target": target,
                        "target_alt": target_alt,
                        "language": code,
                        "category": _value_at(row, category_idx) if category_idx is not None else "",
                        "note": _value_at(row, note_idx) if note_idx is not None else "",
                    }
                )
        return rows, {
            "term_key": headers[term_key_idx] if term_key_idx is not None else "",
            "source": headers[source_idx],
            "languages": {code: {"target": headers[target_idx], "target_alt": headers[alt_idx] if alt_idx is not None else ""} for code, (target_idx, alt_idx) in language_indices.items()},
            "category": headers[category_idx] if category_idx is not None else "",
            "note": headers[note_idx] if note_idx is not None else "",
        }, [code for code in LANGUAGE_ORDER if code in language_indices and any(row.get("language") == code for row in rows)]
    finally:
        wb.close()


def _read_multilingual_translation_rows(
    path: Path,
    sheet: str | None = None,
    id_column: str | None = None,
    source_column: str | None = None,
    note_column: str | None = None,
    source_artifact_id: str = "",
    source_type: str = "imported",
) -> list[dict[str, Any]]:
    if path.suffix.lower() not in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        return []
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        headers = [str(cell.value or "").strip() for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        normalized = _normalized_header_indices(headers)
        id_idx = _column_index(normalized, id_column, ["id", "key", "编号", "序号"], required=False)
        source_idx = _column_index(normalized, source_column, ["source", "original", "cn", "zh", "chinese", "原文", "中文"])
        note_idx = _column_index(normalized, note_column, ["note", "notes", "comment", "备注"], required=False)
        reserved = {index for index in (id_idx, source_idx, note_idx) if index is not None}
        language_indices = _auto_language_indices(headers, reserved)
        if not language_indices:
            return []
        rows: list[dict[str, Any]] = []
        for row_index, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            source = _value_at(row, source_idx)
            if not source:
                continue
            for code, (target_idx, alt_idx) in language_indices.items():
                target = _value_at(row, target_idx)
                target_alt = _value_at(row, alt_idx) if code == "en" else ""
                if not target and not target_alt:
                    continue
                rows.append(
                    {
                        "entry_key": _value_at(row, id_idx) if id_idx is not None else "",
                        "source": source,
                        "target": target,
                        "target_alt": target_alt,
                        "language": code,
                        "sheet": ws.title,
                        "row_number": row_index,
                        "note": _value_at(row, note_idx) if note_idx is not None else "",
                        "source_type": source_type,
                        "source_artifact_id": source_artifact_id,
                    }
                )
        return rows
    finally:
        wb.close()


def _read_translation_rows(
    path: Path,
    sheet: str | None = None,
    id_column: str | None = None,
    source_column: str | None = None,
    target_column: str | None = None,
    target_alt_column: str | None = None,
    note_column: str | None = None,
    language: str = "en",
    source_artifact_id: str = "",
    source_type: str = "imported",
) -> list[dict[str, Any]]:
    language = require_supported_language(language)
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_rows = payload.get("entries") if isinstance(payload, dict) else payload
        rows = []
        for row in (raw_rows or []):
            if not isinstance(row, dict):
                continue
            normalized = {str(key or "").strip().lower(): value for key, value in row.items()}
            rows.append(_translation_row_from_mapping(normalized, int(row.get("row_number") or 0), str(row.get("sheet") or "").strip(), language, source_artifact_id, source_type))
        return rows
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = []
            for index, row in enumerate(reader, start=2):
                normalized = {str(key or "").strip().lower(): value for key, value in row.items()}
                rows.append(_translation_row_from_mapping(normalized, index, "", language, source_artifact_id, source_type))
            return rows

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        headers = [str(cell.value or "").strip() for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        normalized = {header.lower(): index for index, header in enumerate(headers) if header}
        id_idx = _column_index(normalized, id_column, ["id", "key", "编号", "序号"], required=False)
        source_idx = _column_index(normalized, source_column, ["source", "original", "cn", "zh", "chinese", "原文", "中文"])
        target_idx = _column_index(normalized, target_column, target_aliases(language))
        target_alt_idx = _column_index(normalized, target_alt_column, alt_aliases(language), required=False)
        note_idx = _column_index(normalized, note_column, ["note", "notes", "comment", "备注"], required=False)
        rows = []
        for row_index, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            source = _value_at(row, source_idx)
            target = _value_at(row, target_idx)
            if not source and not target:
                continue
            rows.append(
                {
                    "entry_key": _value_at(row, id_idx) if id_idx is not None else "",
                    "source": source,
                    "target": target,
                    "target_alt": _value_at(row, target_alt_idx) if target_alt_idx is not None else "",
                    "language": language,
                    "sheet": ws.title,
                    "row_number": row_index,
                    "note": _value_at(row, note_idx) if note_idx is not None else "",
                    "source_type": source_type,
                    "source_artifact_id": source_artifact_id,
                }
            )
        return rows
    finally:
        wb.close()


def _translation_row_from_mapping(
    row: dict[str, Any],
    row_number: int,
    sheet: str,
    language: str,
    source_artifact_id: str,
    source_type: str,
) -> dict[str, Any]:
    language = require_supported_language(language)
    def pick(*names: str) -> str:
        for name in names:
            value = row.get(name.lower())
            if value not in (None, ""):
                return str(value).strip()
        return ""

    return {
        "entry_key": pick("id", "key", "entry_key", "编号", "序号"),
        "source": pick("cn", "source", "original", "原文", "中文"),
        "target": pick("target", *target_aliases(language)),
        "target_alt": pick("target_alt", *alt_aliases(language)),
        "language": language,
        "sheet": sheet,
        "row_number": row_number,
        "note": pick("note", "notes", "comment", "备注"),
        "source_type": source_type,
        "source_artifact_id": source_artifact_id,
    }


def _translation_export_payload(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "entry_key": entry.get("entry_key", ""),
        "source": entry.get("source", ""),
        "target": entry.get("target", ""),
        "target_alt": entry.get("target_alt", ""),
        "language": entry.get("language", "en"),
        "note": entry.get("note", ""),
    }


def _translation_export_row(entry: dict[str, Any], *, include_alt: bool = True) -> list[Any]:
    row = [
        entry.get("entry_key", ""),
        entry.get("source", ""),
        entry.get("target", ""),
    ]
    if include_alt:
        row.append(entry.get("target_alt", ""))
    row.append(entry.get("note", ""))
    return row


def _translation_wide_export_rows(wide: dict[str, Any], languages: list[str]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for row in wide["rows"]:
        translations = row.get("translations") or {}
        values = [row.get("entry_key", ""), row.get("source", "")]
        for code in languages:
            entry = translations.get(code) or {}
            values.append(entry.get("target", ""))
            if code == "en":
                values.append(entry.get("target_alt", ""))
        values.append(row.get("note", ""))
        rows.append(values)
    return rows

__all__ = [name for name in globals() if not name.startswith("__")]
