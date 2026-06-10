from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .. import db
from ..config import GLOSSARY_ROOT, REAL_PROVIDERS, TEST_FAKE_PROVIDER, load_settings, normalize_provider_name
from ..languages import language_spec, require_supported_language
from ..providers import call_text, translate_batch
from ..translation_batches import manage_project_prompt_context as _manage_project_prompt_context
from . import jsonl_helpers as _jsonl_helpers
from .common import _CJK_RE, project_dir, run_dir
from .materials import analyze_assets
from .naming import _safe_source_stem, _today_stamp
from .announcement_segments import _read_language_table_rows
from .semantic_qa import _parse_semantic_qa_payload
from .subprocess_runner import parse_key_output, run_subprocess, user_facing_error
from .table_helpers import _read_glossary_rows


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

__all__ = [name for name in globals() if not name.startswith("__")]
